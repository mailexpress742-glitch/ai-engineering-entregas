---
categoria: utilidades
etiquetas: context-manager, with, closing
---
# Módulo `contextlib`

Utilities for with-statement contexts.  See PEP 343.

## función `contextlib.asynccontextmanager(func)`

@asynccontextmanager decorator.

Typical usage:

    @asynccontextmanager
    async def some_async_generator(<arguments>):
        <setup>
        try:
            yield <value>
        finally:
            <cleanup>

This makes this:

    async with some_async_generator(<arguments>) as <variable>:
        <body>

equivalent to this:

    <setup>
    try:
        <variable> = <value>
        <body>
    finally:
        <cleanup>

## función `contextlib.contextmanager(func)`

@contextmanager decorator.

Typical usage:

    @contextmanager
    def some_generator(<arguments>):
        <setup>
        try:
            yield <value>
        finally:
            <cleanup>

This makes this:

    with some_generator(<arguments>) as <variable>:
        <body>

equivalent to this:

    <setup>
    try:
        <variable> = <value>
        <body>
    finally:
        <cleanup>

## clase `contextlib.closing(thing)`

Context to automatically close something at the end of a block.

Code like this:

    with closing(<module>.open(<arguments>)) as f:
        <block>

is equivalent to this:

    f = <module>.open(<arguments>)
    try:
        <block>
    finally:
        f.close()

## clase `contextlib.nullcontext(enter_result=None)`

Context manager that does no additional processing.

Used as a stand-in for a normal context manager, when a particular
block of code is only sometimes used with a normal context manager:

cm = optional_cm if condition else nullcontext()
with cm:
    # Perform operation, using optional_cm if condition is True

## clase `contextlib.AbstractContextManager()`

An abstract base class for context managers.

## clase `contextlib.AbstractAsyncContextManager()`

An abstract base class for asynchronous context managers.

## clase `contextlib.AsyncExitStack()`

Async context manager for dynamic management of a stack of exit
callbacks.

For example:
    async with AsyncExitStack() as stack:
        connections = [await stack.enter_async_context(get_connection())
            for i in range(5)]
        # All opened connections will automatically be released at the
        # end of the async with statement, even if attempts to open a
        # connection later in the list raise an exception.

### método `AsyncExitStack.aclose(self)`

Immediately unwind the context stack.

### método `AsyncExitStack.enter_async_context(self, cm)`

Enters the supplied async context manager.

If successful, also pushes its __aexit__ method as a callback and
returns the result of the __aenter__ method.

### método `AsyncExitStack.push_async_callback(self, callback, /, *args, **kwds)`

Registers an arbitrary coroutine function and arguments.

Cannot suppress exceptions.

### método `AsyncExitStack.push_async_exit(self, exit)`

Registers a coroutine function with the standard __aexit__ method
signature.

Can suppress exceptions the same way __aexit__ method can.
Also accepts any object with an __aexit__ method (registering a call
to the method instead of the object itself).

## clase `contextlib.ContextDecorator()`

A base class or mixin that enables context managers to work as decorators.

## clase `contextlib.ExitStack()`

Context manager for dynamic management of a stack of exit callbacks.

For example:
    with ExitStack() as stack:
        files = [stack.enter_context(open(fname)) for fname in filenames]
        # All opened files will automatically be closed at the end of
        # the with statement, even if attempts to open files later
        # in the list raise an exception.

### método `ExitStack.close(self)`

Immediately unwind the context stack.

## clase `contextlib.redirect_stdout(new_target)`

Context manager for temporarily redirecting stdout to another file.

# How to send help() to stderr
with redirect_stdout(sys.stderr):
    help(dir)

# How to write help() to a file
with open('help.txt', 'w') as f:
    with redirect_stdout(f):
        help(pow)

## clase `contextlib.redirect_stderr(new_target)`

Context manager for temporarily redirecting stderr to another file.

## clase `contextlib.suppress(*exceptions)`

Context manager to suppress specified exceptions

After the exception is suppressed, execution proceeds with the next
statement following the with statement.

     with suppress(FileNotFoundError):
         os.remove(somefile)
     # Execution still resumes here if the file was already removed

## clase `contextlib.aclosing(thing)`

Async context manager for safely finalizing an asynchronously cleaned-up
resource such as an async generator, calling its ``aclose()`` method.

Code like this:

    async with aclosing(<module>.fetch(<arguments>)) as agen:
        <block>

is equivalent to this:

    agen = <module>.fetch(<arguments>)
    try:
        <block>
    finally:
        await agen.aclose()

## clase `contextlib.chdir(path)`

Non thread-safe context manager to change the current working directory.
