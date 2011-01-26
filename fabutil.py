'''Utilities for fabric.

For some functions, you may need to provide the global fabric environment with
some information, e.g.::

    import fabutil
    ...
    fabutil.env = env

    # Optional, defaults to 1.5.1 release of virtualenv
    env.ve_source = 'http://.../virtualenv.py'
    env.env_root = '/path/to/virtual-env/root/'
'''
import os
import random
import tempfile
from fabric.api import run, put, cd, env, settings
from fabric.contrib import files


VE_URL = 'http://bitbucket.org/ianb/virtualenv/raw/eb94c9ebe0ba/virtualenv.py'


def vrun(command):
    'Run a command with the virtual environment activated.'
    source = 'source "%(env_root)s/bin/activate" && '
    run(' '.join((source, command)) % env)


def install_bash_aliases(initfile='.profile'):
    "Install some helper utilities and aliases."
    aliases = [
        'alias psa="ps faux |egrep ^`egrep ^$USER /etc/passwd | cut -f3 -d:`"',
        'alias activate="source ~/bin/activate"',
    ]

    files.append(aliases, initfile)


def kill(pidfile, rmpid=True, sig=''):
    if files.exists(pidfile):
        run('kill -%s `cat "%s"`' % (sig, pidfile))
        if rmpid:
            run('rm -f "%s"' % (pidfile,))
    else:
        print 'WARNING: PID file %s does not exist!' % pidfile


def sed(file, sedexpr):
    'Run a sed expression ``sedexpr`` in-place on ``file``.'
    run('sed -i\'\' "%s" "%s"' % (sedexpr, file))


def strput(text, target):
    'Put the contents of the string ``text`` into remote file ``target``.'
    df = tempfile.NamedTemporaryFile()
    df.write(text)
    df.flush()
    put(df.name, target)
    # Must be performed last as closing deletes the temp. file.
    df.close()


def bootstrap_ve(python='python', require=None):
    'Bootstrap a Python environment and install dependencies.'
    context = {
        'staging_dir': os.path.join('/var/tmp', str(random.random())),
        've_source': getattr(env, 've_source', VE_URL),
    }
    env.update(context)
    run('mkdir -p %(staging_dir)s' % env)
    with cd(env.staging_dir):
        run('curl -L "%(ve_source)s" > virtualenv.py' % env)
        run(' '.join((python,
                      'virtualenv.py --clear',
                      '--no-site-packages',
                      '--distribute',
                      env.env_root)))
    if require is not None:
        put(require, env.staging_dir)
        vrun('pip install -r %(staging_dir)s/requirements.txt' % env)
        run('rm -r "%(staging_dir)s"' % env)
        run('mkdir -p %(env_root)s/{etc,var,tmp}' % env)


def install_nginx(src='http://nginx.org/download/nginx-0.8.52.tar.gz'):
    '''Install nginx web server in the virtual environment.

    Minimally, you'll need libpcre3-dev libglobus-openssl-dev for Ubuntu or the
    equivalent on some other distribution.
    '''

    ng_distro = os.path.basename(src)
    for ext, topts in (
            ('.tar', 'xf'),
            ('.tar.gz', 'zxf'),
            ('.tgz', 'zxf'),
            ('.tar.bz2', 'jxf'),
            ('.tbz2', 'jxf')):
        if ng_distro.endswith(ext):
            ng_src_dir = ng_distro.rstrip(ext)
            untar_opts = topts
            break

    with cd(os.path.join(env.env_root, 'src')):
        run('wget "%s"' % src)
        run(' '.join(('tar', untar_opts, ng_distro)))

    with cd(os.path.join(env.env_root, 'src', ng_src_dir)):
        run('./configure'
            ' --with-http_stub_status_module'
            ' --prefix=%(env_root)s'
            ' --sbin-path=%(env_root)s/bin/nginx'
            ' --pid-path=%(env_root)s/var/nginx.pid'
            ' --http-client-body-temp-path=%(env_root)s/tmp/http_client_body_temp/'
            ' --http-proxy-temp-path=%(env_root)s/tmp/proxy_temp/'
            ' --http-fastcgi-temp-path=%(env_root)s/tmp/fastcgi_temp/'
            ' --http-uwsgi-temp-path=%(env_root)s/tmp/uwsgi_temp/'
            ' --http-scgi-temp-path=%(env_root)s/tmp/scgi_temp/'
            ' --conf-path=%(env_root)s/etc/nginx/nginx.conf' % env)
        run('make')
        run('make install')


# Some management commands follow:


def _sighup(pid):
    kill(pid, sig='HUP', rmpid=False)



def start_stack():
    'Alias for: start_nginx start_uwsgi'
    start_nginx()
    start_uwsgi()


def stop_stack():
    'Alias for: kill_nginx kill_uwsgi'
    kill_nginx()
    kill_uwsgi()


def start_nginx():
    '''Start web server.

    TERM/INT: Quick shutdown
    QUIT: Graceful shutdown
    HUP: Configuration reload; Start the new worker processes with a new
         configuration and gracefully shutdown the old worker processes
         USR1 Reopen the log files
    USR2: Upgrade Executable on the fly
    WINCH: Gracefully shutdown the worker processes

    http://wiki.nginx.org/CommandLine
    '''
    kill(os.path.join(env.env_root, 'var', 'nginx.pid'), sig='QUIT')
    vrun('nginx')


def sighup_nginx():
    'Gracefully restart nginx.'
    _sighup(os.path.join(env.env_root, 'var', 'nginx.pid'))


def kill_nginx():
    'Stop nginx.'
    kill(os.path.join(env.env_root, 'var', 'nginx.pid'), sig='QUIT')


def start_uwsgi():
    '''Start uWSGI.

    The uWSGI server responds to this signals[1]:

    SIGHUP: reload (gracefully) all the workers and the master process
    SIGTERM: brutally reload all the workers and the master process
    SIGINT/SIGQUIT: kill all the uWSGI stack
    SIGUSR1: print statistics

    [1] http://projects.unbit.it/uwsgi/wiki/uWSGISignals
    '''

    # Note!  Need to start uWSGI with the full path to the binary.
    # > This is caused by your binary path changing after startup.
    # > For example you start uwsgi with
    # > ./uwsgi
    # > in directory /tmp than you chdir to something else.
    # > When uWSGI restarts ./uwsgi is no more valid.  There are other cases but
    # > they are all fixed in the patch 0966_0967 that you will find in the list
    # > archives, or you can wait til tomorrow when uwsgi-0.9.6.7 will be
    # > released.
    if files.exists(os.path.join(env.env_root, 'var', 'uwsgi.pid')):
        print 'PID File exists, running sighup_uwsgi()'
        sighup_uwsgi()
    else:
        vrun('%(env_root)s/bin/uwsgi'
             ' --ini %(env_root)s/etc/uwsgi.ini'
             ' -d %(env_root)s/logs/uwsgi.log' % env)

def kill_uwsgi():
    'Stop uWSGI master and worker processes.'
    kill(os.path.join(env.env_root, 'var', 'uwsgi.pid'), sig='SIGINT')


def sighup_uwsgi():
    'Gracefully restart uWSGI.'
    _sighup(os.path.join(env.env_root, 'var', 'uwsgi.pid'))


def copytree(source, destroot, mkdir=True, excl=[], exclfunc=lambda x: False):
    '''
    Copy the contents of a directory tree.

    If ``mkdir`` is True, the destination directory will be created on the
    remote host.  ``excl`` is a list of file names to be excluded (note this
    function compares it with the source **path**).  For more complex logic you
    can specify a function ``exclfunc`` taking the source path and returning a
    True if the src path should be exluded.
    '''
    if mkdir is True:
        run('mkdir -p %s' % destroot)
    dircache = set()
    for dpath, dnames, fnames in os.walk(source):
        for f in fnames:
            src = os.path.join(dpath, f)
            target = os.path.join(destroot, src)

            if src in excl:
                continue
            if exclfunc(src) is True:
                continue
            if dpath not in dircache:
                run('mkdir -p %s' % os.path.join(destroot, dpath))
                dircache.add(dpath)
            put(src, target)
