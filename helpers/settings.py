settings_path = 'settings.conf'

def load(interactive=True):
    import getpass
    import ConfigParser as configparser
    import subprocess
    from . import utilities

    # Parse the settings file.

    parser = configparser.SafeConfigParser()
    parser.read(settings_path)

    # Read all the settings from the config file.

    global rosetta, author, db_name, db_user, db_password, db_host, db_port

    def get_setting(parser, section, setting, prompt, default=None):
        try:
            # Attempt to read the requested setting from the settings file.
            return parser.get(section, setting)

        except configparser.Error:

            # If not in interactive mode, each setting must have a value.
            if not interactive: raise

            # Prompt the user for the missing value.
            if get_setting.first_prompt:
                get_setting.first_prompt = False
                print '''\
Settings related to running and analyzing the loop modeling benchmark are kept 
in 'settings.conf'.  Values for the following settings are needed:
'''
            if default:
                prompt += ' [{0}]'.format(default)

            try:
                value = raw_input(prompt + ': ') or default
            except KeyboardInterrupt:
                print
                raise SystemExit

            # Add the setting to the ConfigFile object.
            if not parser.has_section(section):
                parser.add_section(section)

            parser.set(section, setting, value)

            # Update the settings file.
            with open(settings_path, 'w') as file:
                parser.write(file)

            return value


    get_setting.first_prompt = True

    rosetta = get_setting(parser, 'rosetta', 'path', prompt="Path to rosetta")
    author = get_setting(parser, 'analysis', 'author', prompt="Your full name")
    db_name = get_setting(parser, 'database', 'name', prompt="Database name", default='loops_modeling_benchmark')
    db_user = get_setting(parser, 'database', 'user', prompt="Database user", default=getpass.getuser())
    db_password_cmd = get_setting(parser, 'database', 'password', prompt="Command to get database password", default='echo pa55w0rd')
    db_host = get_setting(parser, 'database', 'host', prompt="Database host", default='guybrush-pi.compbio.ucsf.edu')
    db_port = get_setting(parser, 'database', 'port', prompt="Database port", default='3306')

    # Invoke the password command to get the database password.

    db_password = subprocess.check_output(db_password_cmd, shell=True).strip()


# These values are filled in by the install() and load() functions.

rosetta = ''
author = ''
db_name = ''
db_user = ''
db_password = ''
db_host = ''
db_port = ''
