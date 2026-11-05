---
categoria: concurrencia
etiquetas: asyncio, taskgroup, cancelacion
---
# Módulo `asyncio.taskgroups`



## clase `asyncio.taskgroups.TaskGroup()`

Asynchronous context manager for managing groups of tasks.

Example use:

    async with asyncio.TaskGroup() as group:
        task1 = group.create_task(some_coroutine(...))
        task2 = group.create_task(other_coroutine(...))
    print("Both tasks have completed now.")

All tasks are awaited when the context manager exits.

Any exceptions other than `asyncio.CancelledError` raised within
a task will cancel all remaining tasks and wait for them to exit.
The exceptions are then combined and raised as an `ExceptionGroup`.

### método `TaskGroup.create_task(self, coro, *, name=None, context=None)`

Create a new task in this group and return it.

Similar to `asyncio.create_task`.
