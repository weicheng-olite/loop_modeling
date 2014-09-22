#!/usr/bin/env python2

"""\
Launch a loops benchmark run.  Options are provided so you can easily control 
every important aspect of the benchmark, including which protocol to test, 
which structures to use, and how much simulation to do one each one.  The 
benchmark results are written to the MySQL database specified in the settings 
file to facilitate storage and organization.  This script automatically 
compiles rosetta with database support before each run.

Usage:
    kickoff.py <name> <script> <pdbs>... [--var=VAR ...] [options]
    kickoff.py --resume ID [options]

Arguments:
    <name>
        The name for this benchmark.  It's ok for several benchmark runs to 
        have the same name.  The analysis script will automatically pick the 
        most recent one when given an ambiguous name.

    <script>
        A rosetta XML script to execute.  Commonly used scripts can be found in 
        the benchmarks directory of this repository.  Feel free to add more!

    <pdbs>
        A list of PDB files to use for the benchmark.  Files with the extension 
        '*.pdbs' are expected to contain a list of PDB files to include (one on 
        each line).  Commonly used PDB lists can be found in the benchmarks 
        directory of this repository.

Options:
    --var VAR
        Specify a rosetta-scripts macro substitution to make.  This option can 
        be specified any number of times.  Each instance of this option should 
        specify and name and a value like so: "--var name=value".

    --flags OPT
        Specify a rosetta flag file containing extra options for this run.

    --nstruct NUM -n NUM
        Specify how many simulations to do for each structure in the benchmark.
        The default value is 500.

    --desc DESC -m DESC
        Give a more detailed description of this benchmark run.

    --compile-only
        Compile rosetta but don't run the benchmark.

    --execute-only -x
        Launch the benchmark without compiling rosetta.  I never use this flag 
        when launching full-scale benchmarks, but for test runs it's not worth 
        waiting 2-3 minutes for scons to figure out that nothing has changed.

    --fast
        Run jobs with a very small number of iterations and lower the default 
        value of --nstruct to 10.  This is useful when you're just making sure 
        a new algorithm runs without crashing.

    --resume ID -r ID
        Expand the given benchmark by running more jobs.  The new jobs will use 
        the same PDB files, rosetta script files, rosetta script variables, 
        rosetta flag files, and "fast" settings as the previous jobs did.  
        However, results may differ if the contents of these files, or the 
        checked out version of rosetta, are changed.
"""

import sys
import os
import shutil
import subprocess
import glob
import json
import getpass

from libraries import utilities; utilities.require_chef()
from libraries import settings; settings.load()
from libraries import database

def compile_rosetta():
    rosetta_path = os.path.abspath(settings.rosetta)

    # Setup the compiler for the cluster.

    qb3_settings = os.path.join(
            rosetta_path, 'source', 'tools', 'build', 'site.settings.qb3')
    site_settings = os.path.join(
            rosetta_path, 'source', 'tools', 'build', 'site.settings')

    shutil.copyfile(qb3_settings, site_settings)

    # Copy the mysql header files into rosetta.

    mysql_headers = (
            '/netapp/home/kbarlow/lib/'
            'mysql-connector-c-6.1.2-linux-glibc2.5-x86_64/include/*')
    rosetta_headers = os.path.join(
            rosetta_path, 'source', 'external', 'dbio', 'mysql')
    
    for source_path in glob.glob(mysql_headers):
        target_name = os.path.basename(source_path)
        target_path = os.path.join(rosetta_headers, target_name)
        if not os.path.exists(target_path):
            os.symlink(source_path, target_path)

    # Compile rosetta.

    scons_path = os.path.join(rosetta_path, 'source')

    compile_command = 'ssh', 'iqint', '; '.join([
            'cd "%s"' % scons_path,
            'nohup nice ./scons.py bin -j16 mode=release extras=mysql'])

    return subprocess.call(compile_command)

def run_benchmark(name, script, pdbs,
        vars=(), flags=None, nstruct=None, desc=None, fast=False):

    pdbs = [x for x in sorted(pdbs)]

    # Make sure all the inputs actually exist.

    for pdb in pdbs:
        if not os.path.exists(pdb):
            raise ValueError("'{0}' does not exist.".format(pdb))

    # Create an entry in the benchmarks table.

    with database.connect() as session:
        benchmark = database.Benchmarks(
                name, script,
                user=getpass.getuser(), desc=desc,
                vars=json.dumps(vars), flags=flags, fast=fast
        )

        for pdb in pdbs:
            benchmark_input = database.BenchmarkInputs(pdb)
            benchmark.input_pdbs.append(benchmark_input)

        session.add(benchmark); session.flush()
        benchmark_id = str(benchmark.id)

    print "Your benchmark \"{0}\" (id={1}) has been created".format(
            name, benchmark_id)

    # Submit the benchmark to the cluster.

    qsub_command = 'qsub',
    benchmark_command = 'loop_benchmark.py', benchmark_id

    if nstruct is not None: assert isinstance(nstruct, int)

    if fast:
        qsub_command += '-t', '1-{0}'.format((nstruct or 10) * len(pdbs))
        qsub_command += '-l', 'h_rt=0:30:00'
    else:
        qsub_command += '-t', '1-{0}'.format((nstruct or 500) * len(pdbs))
        qsub_command += '-l', 'h_rt=4:00:00'

    utilities.clear_directory('job_output')
    qsub_command += '-o', 'job_output', '-e', 'job_output'

    subprocess.call(qsub_command + benchmark_command)

def resume_benchmark(benchmark_id, nstruct=None):
    qsub_command = 'qsub',
    benchmark_command = 'loop_benchmark.py', benchmark_id

    # You get weird errors if you forget to cast nstruct from string to int.
    if nstruct is not None: assert isinstance(nstruct, int)

    with database.connect() as session:
        benchmark = session.query(database.Benchmarks).get(benchmark_id)
        num_pdbs = len(benchmark.input_pdbs)

        if benchmark.fast:
            qsub_command += '-t', '1-{0}'.format((nstruct or 10) * num_pdbs)
            qsub_command += '-l', 'h_rt=0:30:00'
        else:
            qsub_command += '-t', '1-{0}'.format((nstruct or 500) * num_pdbs)
            qsub_command += '-l', 'h_rt=4:00:00'
    
        print "Your benchmark \"{0}\" (id={1}) is being resumed".format(
                benchmark.name, benchmark_id)

    utilities.clear_directory('job_output')
    qsub_command += '-o', 'job_output', '-e', 'job_output'

    subprocess.call(qsub_command + benchmark_command)


if __name__ == '__main__':
    from libraries import docopt

    # Parse command-line options.

    arguments = docopt.docopt(__doc__)

    # Compile rosetta.

    if not arguments['--execute-only']:
        error_code = compile_rosetta()
        if error_code != 0:
            sys.exit(error_code)

    if arguments['--compile-only']:
        sys.exit(1)

    # Decide whether to start a new benchmark or to resume an old one.

    if arguments['--resume'] is not None:
        benchmark_id = arguments['--resume']
        resume_benchmark(benchmark_id, int(arguments['--nstruct']))
    
    else:
        name = arguments['<name>']
        script = arguments['<script>']
        pdb_args, pdbs = set(arguments['<pdbs>']), set()

        # Decide which structures to benchmark.

        for path in pdb_args:
            if path.endswith('.pdb') or path.endswith('.pdb.gz'):
                pdbs.add(path)

            elif path.endswith('.pdbs'):
                with open(path) as file:
                    pdbs.update(line.strip() for line in file)

            else:
                print "Unknown input structure '{0}'.".format(path)
                sys.exit(1)

        for pdb in pdbs:
            if not os.path.exists(pdb):
                print "Unknown input structure '{0}'.".format(pdb)
                sys.exit(1)

        # Run the benchmark.

        run_benchmark(
                name, script, pdbs,
                vars=arguments['--var'],
                flags=arguments['--flags'],
                nstruct=int(arguments['--nstruct']),
                desc=arguments['--desc'],
                fast=arguments['--fast'],
        )

