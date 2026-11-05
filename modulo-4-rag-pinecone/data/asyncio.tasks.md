---
categoria: concurrencia
etiquetas: asyncio, tareas, gather, timeout
---
# Módulo `asyncio.tasks`

Support for tasks, coroutines and the scheduler.

## función `asyncio.tasks.create_task(coro, *, name=None, context=None)`

Schedule the execution of a coroutine object in a spawn task.

Return a Task object.

## función `asyncio.tasks.wait(fs, *, timeout=None, return_when='ALL_COMPLETED')`

Wait for the Futures or Tasks given by fs to complete.

The fs iterable must not be empty.

Coroutines will be wrapped in Tasks.

Returns two sets of Future: (done, pending).

Usage:

    done, pending = await asyncio.wait(fs)

Note: This does not raise TimeoutError! Futures that aren't done
when the timeout occurs are returned in the second set.

## función `asyncio.tasks.wait_for(fut, timeout)`

Wait for the single Future or coroutine to complete, with timeout.

Coroutine will be wrapped in Task.

Returns result of the Future or coroutine.  When a timeout occurs,
it cancels the task and raises TimeoutError.  To avoid the task
cancellation, wrap it in shield().

If the wait is cancelled, the task is also cancelled.

If the task suppresses the cancellation and returns a value instead,
that value is returned.

This function is a coroutine.

## función `asyncio.tasks.as_completed(fs, *, timeout=None)`

Return an iterator whose values are coroutines.

When waiting for the yielded coroutines you'll get the results (or
exceptions!) of the original Futures (or coroutines), in the order
in which and as soon as they complete.

This differs from PEP 3148; the proper way to use this is:

    for f in as_completed(fs):
        result = await f  # The 'await' may raise.
        # Use result.

If a timeout is specified, the 'await' will raise
TimeoutError when the timeout occurs before all Futures are done.

Note: The futures 'f' are not necessarily members of fs.

## función `asyncio.tasks.sleep(delay, result=None)`

Coroutine that completes after a given time (in seconds).

## función `asyncio.tasks.gather(*coros_or_futures, return_exceptions=False)`

Return a future aggregating results from the given coroutines/futures.

Coroutines will be wrapped in a future and scheduled in the event
loop. They will not necessarily be scheduled in the same order as
passed in.

All futures must share the same event loop.  If all the tasks are
done successfully, the returned future's result is the list of
results (in the order of the original sequence, not necessarily
the order of results arrival).  If *return_exceptions* is True,
exceptions in the tasks are treated the same as successful
results, and gathered in the result list; otherwise, the first
raised exception will be immediately propagated to the returned
future.

Cancellation: if the outer Future is cancelled, all children (that
have not completed yet) are also cancelled.  If any child is
cancelled, this is treated as if it raised CancelledError --
the outer Future is *not* cancelled in this case.  (This is to
prevent the cancellation of one child to cause other children to
be cancelled.)

If *return_exceptions* is False, cancelling gather() after it
has been marked done won't cancel any submitted awaitables.
For instance, gather can be marked done after propagating an
exception to the caller, therefore, calling ``gather.cancel()``
after catching an exception (raised by one of the awaitables) from
gather won't cancel any other awaitables.

## función `asyncio.tasks.shield(arg)`

Wait for a future, shielding it from cancellation.

The statement

    task = asyncio.create_task(something())
    res = await shield(task)

is exactly equivalent to the statement

    res = await something()

*except* that if the coroutine containing it is cancelled, the
task running in something() is not cancelled.  From the POV of
something(), the cancellation did not happen.  But its caller is
still cancelled, so the yield-from expression still raises
CancelledError.  Note: If something() is cancelled by other means
this will still cancel shield().

If you want to completely ignore cancellation (not recommended)
you can combine shield() with a try/except clause, as follows:

    task = asyncio.create_task(something())
    try:
        res = await shield(task)
    except CancelledError:
        res = None

Save a reference to tasks passed to this function, to avoid
a task disappearing mid-execution. The event loop only keeps
weak references to tasks. A task that isn't referenced elsewhere
may get garbage collected at any time, even before it's done.

## función `asyncio.tasks.ensure_future(coro_or_future, *, loop=None)`

Wrap a coroutine or an awaitable in a future.

If the argument is a Future, it is returned directly.

## función `asyncio.tasks.run_coroutine_threadsafe(coro, loop)`

Submit a coroutine object to a given event loop.

Return a concurrent.futures.Future to access the result.

## función `asyncio.tasks.all_tasks(loop=None)`

Return a set of all tasks for the loop.

## función `asyncio.tasks.create_eager_task_factory(custom_task_constructor)`

Create a function suitable for use as a task factory on an event-loop.

Example usage:

    loop.set_task_factory(
        asyncio.create_eager_task_factory(my_task_constructor))

Now, tasks created will be started immediately (rather than being first
scheduled to an event loop). The constructor argument can be any callable
that returns a Task-compatible object and has a signature compatible
with `Task.__init__`; it must have the `eager_start` keyword argument.

Most applications will use `Task` for `custom_task_constructor` and in
this case there's no need to call `create_eager_task_factory()`
directly. Instead the  global `eager_task_factory` instance can be
used. E.g. `loop.set_task_factory(asyncio.eager_task_factory)`.
