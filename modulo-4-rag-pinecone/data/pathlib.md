---
categoria: archivos_y_datos
etiquetas: rutas, archivos, path
---
# Módulo `pathlib`

Object-oriented filesystem paths.

This module provides classes to represent abstract paths and concrete
paths with operations that have semantics appropriate for different
operating systems.

## clase `pathlib.PurePath(*args, **kwargs)`

Base class for manipulating paths without I/O.

PurePath represents a filesystem path and offers operations which
don't imply any actual filesystem I/O.  Depending on your system,
instantiating a PurePath will return either a PurePosixPath or a
PureWindowsPath object.  You can also instantiate either of these classes
directly, regardless of your system.

### método `PurePath.as_posix(self)`

Return the string representation of the path with forward (/)
slashes.

### método `PurePath.as_uri(self)`

Return the path as a 'file' URI.

### método `PurePath.is_absolute(self)`

True if the path is absolute (has both a root and, if applicable,
a drive).

### método `PurePath.is_relative_to(self, other, /, *_deprecated)`

Return True if the path is relative to another path or False.
        

### método `PurePath.is_reserved(self)`

Return True if the path contains one of the special names reserved
by the system, if any.

### método `PurePath.joinpath(self, *pathsegments)`

Combine this path with one or several arguments, and return a
new path representing either a subpath (if all arguments are relative
paths) or a totally different path (if one of the arguments is
anchored).

### método `PurePath.match(self, path_pattern, *, case_sensitive=None)`

Return True if this path matches the given pattern.

### método `PurePath.relative_to(self, other, /, *_deprecated, walk_up=False)`

Return the relative path to another path identified by the passed
arguments.  If the operation is not possible (because this is not
related to the other path), raise ValueError.

The *walk_up* parameter controls whether `..` may be used to resolve
the path.

### método `PurePath.with_name(self, name)`

Return a new path with the file name changed.

### método `PurePath.with_segments(self, *pathsegments)`

Construct a new path object from any number of path-like objects.
Subclasses may override this method to customize how new path objects
are created from methods like `iterdir()`.

### método `PurePath.with_stem(self, stem)`

Return a new path with the stem changed.

### método `PurePath.with_suffix(self, suffix)`

Return a new path with the file suffix changed.  If the path
has no suffix, add given suffix.  If the given suffix is an empty
string, remove the suffix from the path.

## clase `pathlib.PurePosixPath(*args, **kwargs)`

PurePath subclass for non-Windows systems.

On a POSIX system, instantiating a PurePath should return this object.
However, you can also instantiate it directly on any system.

## clase `pathlib.PureWindowsPath(*args, **kwargs)`

PurePath subclass for Windows systems.

On a Windows system, instantiating a PurePath should return this object.
However, you can also instantiate it directly on any system.

## clase `pathlib.Path(*args, **kwargs)`

PurePath subclass that can make system calls.

Path represents a filesystem path but unlike PurePath, also offers
methods to do system calls on path objects. Depending on your system,
instantiating a Path will return either a PosixPath or a WindowsPath
object. You can also instantiate a PosixPath or WindowsPath directly,
but cannot instantiate a WindowsPath on a POSIX system or vice versa.

### método `Path.absolute(self)`

Return an absolute version of this path by prepending the current
working directory. No normalization or symlink resolution is performed.

Use resolve() to get the canonical path to a file.

### método `Path.chmod(self, mode, *, follow_symlinks=True)`

Change the permissions of the path, like os.chmod().

### método `Path.exists(self, *, follow_symlinks=True)`

Whether this path exists.

This method normally follows symlinks; to check whether a symlink exists,
add the argument follow_symlinks=False.

### método `Path.expanduser(self)`

Return a new path with expanded ~ and ~user constructs
(as returned by os.path.expanduser)

### método `Path.glob(self, pattern, *, case_sensitive=None)`

Iterate over this subtree and yield all existing files (of any
kind, including directories) matching the given relative pattern.

### método `Path.group(self)`

Return the group name of the file gid.

### método `Path.hardlink_to(self, target)`

Make this path a hard link pointing to the same file as *target*.

Note the order of arguments (self, target) is the reverse of os.link's.

### método `Path.is_block_device(self)`

Whether this path is a block device.

### método `Path.is_char_device(self)`

Whether this path is a character device.

### método `Path.is_dir(self)`

Whether this path is a directory.

### método `Path.is_fifo(self)`

Whether this path is a FIFO.

### método `Path.is_file(self)`

Whether this path is a regular file (also True for symlinks pointing
to regular files).

### método `Path.is_junction(self)`

Whether this path is a junction.

### método `Path.is_mount(self)`

Check if this path is a mount point

### método `Path.is_socket(self)`

Whether this path is a socket.

### método `Path.is_symlink(self)`

Whether this path is a symbolic link.

### método `Path.iterdir(self)`

Yield path objects of the directory contents.

The children are yielded in arbitrary order, and the
special entries '.' and '..' are not included.

### método `Path.lchmod(self, mode)`

Like chmod(), except if the path points to a symlink, the symlink's
permissions are changed, rather than its target's.

### método `Path.lstat(self)`

Like stat(), except if the path points to a symlink, the symlink's
status information is returned, rather than its target's.

### método `Path.mkdir(self, mode=511, parents=False, exist_ok=False)`

Create a new directory at this given path.

### método `Path.open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None)`

Open the file pointed to by this path and return a file object, as
the built-in open() function does.

### método `Path.owner(self)`

Return the login name of the file owner.

### método `Path.read_bytes(self)`

Open the file in bytes mode, read it, and close the file.

### método `Path.read_text(self, encoding=None, errors=None)`

Open the file in text mode, read it, and close the file.

### método `Path.readlink(self)`

Return the path to which the symbolic link points.

### método `Path.rename(self, target)`

Rename this path to the target path.

The target path may be absolute or relative. Relative paths are
interpreted relative to the current working directory, *not* the
directory of the Path object.

Returns the new Path instance pointing to the target path.

### método `Path.replace(self, target)`

Rename this path to the target path, overwriting if that path exists.

The target path may be absolute or relative. Relative paths are
interpreted relative to the current working directory, *not* the
directory of the Path object.

Returns the new Path instance pointing to the target path.

### método `Path.resolve(self, strict=False)`

Make the path absolute, resolving all symlinks on the way and also
normalizing it.

### método `Path.rglob(self, pattern, *, case_sensitive=None)`

Recursively yield all existing files (of any kind, including
directories) matching the given relative pattern, anywhere in
this subtree.

### método `Path.rmdir(self)`

Remove this directory.  The directory must be empty.

### método `Path.samefile(self, other_path)`

Return whether other_path is the same or not as this file
(as returned by os.path.samefile()).

### método `Path.stat(self, *, follow_symlinks=True)`

Return the result of the stat() system call on this path, like
os.stat() does.

### método `Path.symlink_to(self, target, target_is_directory=False)`

Make this path a symlink pointing to the target path.
Note the order of arguments (link, target) is the reverse of os.symlink.

### método `Path.touch(self, mode=438, exist_ok=True)`

Create this file with the given access mode, if it doesn't exist.

### método `Path.unlink(self, missing_ok=False)`

Remove this file or link.
If the path is a directory, use rmdir() instead.

### método `Path.walk(self, top_down=True, on_error=None, follow_symlinks=False)`

Walk the directory tree from this directory, similar to os.walk().

### método `Path.write_bytes(self, data)`

Open the file in bytes mode, write to it, and close the file.

### método `Path.write_text(self, data, encoding=None, errors=None, newline=None)`

Open the file in text mode, write to it, and close the file.

## clase `pathlib.PosixPath(*args, **kwargs)`

Path subclass for non-Windows systems.

On a POSIX system, instantiating a Path should return this object.

## clase `pathlib.WindowsPath(*args, **kwargs)`

Path subclass for Windows systems.

On a Windows system, instantiating a Path should return this object.
