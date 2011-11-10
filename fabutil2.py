import getpass
import os
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


def u_h(u, h):
    return '@'.join((u, h))


def get_ec2_cluster(application_group, tagname='application-group'):
    import boto
    c = boto.connect_ec2()
    iids = [t.res_id for t in c.get_all_tags()
            if t.name == tagname and t.value == application_group]
    instances = [i.instances[0] for i in c.get_all_instances(instance_ids=iids)]
    return instances


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
# Management Commands
#


@task
@roles('system-role')
def configure_nginx(conf, name):
    env.nginx_vhost_name = name
    put(conf, '/etc/nginx/sites-available/{nginx_vhost_name}',
        use_sudo=True, template=True)
    sudo('ln -sf /etc/nginx/sites-available/{nginx_vhost_name}'
         ' /etc/nginx/sites-enabled/{nginx_vhost_name}')
    sudo('/etc/init.d/nginx restart')


@task
@roles('web')
def deploy_crontab():
    if env.crontab:
        put(None, '{home}/tmp/crontab', putstr=env.crontab + '\n\n')
        run('crontab {home}/tmp/crontab')


@task
@roles('web')
def sv(cmd, service):
    run('SVDIR={home}/service sv ' + cmd + ' ' + service)


#
# Utility functions
#

@task
@runs_once
def build_packages():
    '''Find setup.py files and run them.
    '''
    # --force-manifest is only available with distutils, not
    # setuptools/distribute.  Sigh.
    base = os.path.abspath('.')
    local('find {0} -name MANIFEST | xargs rm'.format(base))

    base_dirs = []
    dist_dir = os.path.abspath('./dist')
    local('mkdir -p {0}'.format(dist_dir))
    for root, dirs, files in os.walk('.'):
        if 'setup.py' in files:
            base_dirs.append(root)
    for rel_base in base_dirs:
        base = os.path.abspath(rel_base)
        base_dist = os.path.join(base, 'dist')
        local('cd {0} && python setup.py sdist'.format(base))
        if base_dist != dist_dir:
            local('mv {0}/* {1}'.format(base_dist, dist_dir))
            local('rmdir {0}'.format(base_dist))


def sshagent_run(cmd):
    """
    Helper function.
    Runs a command with SSH agent forwarding enabled.

    Note:: Fabric (and paramiko) can't forward your SSH agent.
    This helper uses your system's ssh to do so.
    """
    h = env.host_string
    try:
        # catch the port number to pass to ssh
        host, port = h.split(':')
        local('ssh-add && ssh-add -l && ssh -p %s -A %s "%s"' % (port, host, cmd))
    except ValueError:
        local('ssh-add && ssh-add -l && ssh -A %s "%s"' % (h, cmd))


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
    sudo('mkdir -p {home}/{{shared,service}}')
    sudo('chown -R {acct}:{acct} {home}')
        
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


#
# Local redis setup.
#


@task
@roles('web')
def install_redis(conf='etc/redis.conf.template',
                  src='http://redis.googlecode.com/files/redis-2.2.12.tar.gz'):
    run('mkdir -p {home}/redis/etc/redis')
    run('mkdir -p {home}/redis/src')
    put(conf, '{home}/redis/etc/redis/redis.conf', template=True)
    redis_distro = os.path.basename(src)
    for ext, topts in (
            ('.tar', 'xf'),
            ('.tar.gz', 'zxf'),
            ('.tgz', 'zxf'),
            ('.tar.bz2', 'jxf'),
            ('.tbz2', 'jxf')):
        if redis_distro.endswith(ext):
            redis_src_dir = redis_distro.rstrip(ext)
            untar_opts = topts
            break

    with cd(os.path.join(env.home, 'redis', 'src')):
        run('wget "%s"' % src)
        run(' '.join(('tar', untar_opts, redis_distro)))

    with cd(os.path.join(env.home, 'redis', 'src', redis_src_dir)):
        run('make')
        run('make PREFIX={home}/redis/ install' % env)

    redis_runit_template = (
        '#!/bin/bash\n\n'
        'REDIS={home}/redis/bin/redis-server\n'
        'CONF={home}/redis/etc/redis/redis.conf\n'
        'PID={home}/shared/run/redis.pid\n'
        'if [ -f $PID ]; then rm $PID; fi\n'
        'exec $REDIS $CONF\n')

    run('mkdir -p {home}/service/redis')
    put(None, '{home}/service/redis/run', putstr=redis_runit_template)
    run('chmod 755 {home}/service/redis/run')


@task
@roles('web')
def start_redis():
    'Start Redis database'
    run('SVDIR={home}/service sv start redis')


@task
@roles('web')
def kill_redis():
    'Stop Redis database'
    run('SVDIR={home}/service sv stop redis')
