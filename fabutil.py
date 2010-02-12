import tempfile
import os
from fabric.api import run, put
from fabric.contrib.files import exists


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
