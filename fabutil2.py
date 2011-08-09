import getpass
import socket
import tempfile
from datetime import datetime
from fabric.api import env
from fabric.api import run as fabric_run, sudo as fabric_sudo, local as fabric_local
from fabric.api import put as fabric_put, get as fabric_get, cd as fabric_cd
from fabric.decorators import task, runs_once, roles


def set_defaults():
    'Set default environment values.'
    env.deploy_user = getpass.getuser()
    env.deploy_hostname = socket.gethostname()
    env.format = True
    env.pypi = 'http://pypi.python.org/simple'
    env.python = 'python'
    env.virtualenv = 'virtualenv -p {python} --no-site-packages --distribute'.format(**env)
    env.now = datetime.now().strftime('%Y%m%d%H%M%S')
    env.gitrev = fabric_local('git describe --dirty', capture=True)
    env.base = '{now}-{gitrev}'.format(**env)


#
# Deployment Helpers
#


def formatargs(func):
    def wrapper(*args, **kwargs):
        if getattr(env, 'format', False) is True:
            args = map(lambda x: x.format(**env) if isinstance(x, basestring) else x, args)
        return func(*args, **kwargs)
    return wrapper


def virtualenv(func):
    def wrapper(command, *args, **kwargs):
        if kwargs.pop('virtualenv', False) is True:
            activate = '{home}/releases/{base}/bin/activate'.format(**env)
            command = 'source "%s" && %s' % (activate, command)
        return func(command, *args, **kwargs)
    return wrapper


@virtualenv
@formatargs
def run(command, **kwargs):
    return fabric_run(command, **kwargs)


@virtualenv
@formatargs
def sudo(command, **kwargs):
    return fabric_sudo(command, **kwargs)


@formatargs
def local(command, **kwargs):
    return fabric_local(command, **kwargs)


@formatargs
def put(local_path, remote_path, **kwargs):
    formatted = None
    if 'putstr' in kwargs:
        formatted = kwargs.pop('putstr').format(**env)
    elif kwargs.pop('template', False) is True:
        with open(local_path) as file:
            formatted = file.read().format(**env)

    if formatted is not None:
        (fd, filename) = tempfile.mkstemp()
        with open(filename, 'w') as file:
            file.write(formatted)
            file.flush()
    else:
        filename = local_path
    return fabric_put(filename, remote_path, **kwargs)


@formatargs
def get(remote_path, local_path):
    return fabric_get(remote_path, local_path)


@formatargs
def cd(remote_path):
    return fabric_cd(remote_path)


@task
@runs_once
def print_hosts():
    """Print the list of targets for an environment."""
    for role, hosts in env.roledefs.items():
        print role + ':'
        for host in hosts:
            print '  ' + host


#
# Admin Setup
#


def _setup_system_role_env(acct, home):
    if acct is not None:
        env.acct = acct
    if home is not None:
        env.home = home
    if 'home' not in env:
        env.home = '/srv/' + env.acct


@task
@roles('system-role')
def setup_user(acct=None, home=None):
    _setup_system_role_env(acct, home)
    setup_user_account(acct, home)
    setup_user_runit(acct, home)


@task
@roles('system-role')
def setup_user_account(acct=None, home=None):
    _setup_system_role_env(acct, home)
    sudo('yes "\n" | adduser --shell /bin/bash '
         '--quiet --disabled-password --home {home} {acct}')
    sudo('mkdir -m 700 -p {home}/.ssh')
    # We use $HOME/.ssh/authorized_keys2 for keys managed with this approach.
    if 'authorized_keys' in env:
        auth2 = ('# DO NOT EDIT, MANAGED BY fabfile.py\n' + 
                 '\n'.join(env.authorized_keys))
        put(None, '{home}/.ssh/authorized_keys2',
            putstr=auth2, use_sudo=True)
        sudo('chmod 600 {home}/.ssh/authorized_keys2')
    sudo('chown -R {acct}:{acct} {home}')


@task
@roles('system-role')
def setup_user_runit(acct=None, home=None):
    _setup_system_role_env(acct, home)
    env.runit_log_dir = '{home}/shared/log/runit'.format(**env)
    runfile = ('#!/bin/sh\n'
               'exec 2>&1\n'
               'exec chpst -u{acct} runsvdir {home}/service\n').format(**env)

    runfile_log = ('#!/bin/sh\n'
                   'exec chpst -u{acct} svlogd -tt {runit_log_dir}/\n')
    
    sudo('mkdir -p {runit_log_dir}')
    sudo('chown -R {acct}:{acct} {home}/{service,shared}')
        
    sudo('mkdir -p /etc/service/{acct}/log')
    sudo('mkdir -p /etc/sv/{acct}')
    sudo('ln -sf /etc/service/{acct}/run /etc/sv/{acct}/run')
    sudo('ln -sf /etc/service/{acct}/log /etc/sv/{acct}/log')
    # template=True implied by use of putstr argument.
    put(None, '/etc/service/{acct}/run', putstr=runfile, use_sudo=True)
    put(None, '/etc/service/{acct}/log/run', putstr=runfile_log, use_sudo=True)
    sudo('chown root:root /etc/service/{acct}/run')
    sudo('chown root:root /etc/service/{acct}/log/run')
    sudo('chmod 755 /etc/service/{acct}/run')
    sudo('chmod 755 /etc/service/{acct}/log/run')
