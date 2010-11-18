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
        run('curl "%(ve_source)s" > virtualenv.py' % env)
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
