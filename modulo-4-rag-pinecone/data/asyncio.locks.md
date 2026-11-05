---
categoria: concurrencia
etiquetas: asyncio, locks, semaforo, evento
---
# Módulo `asyncio.locks`

Synchronization primitives.

## clase `asyncio.locks.Lock()`

Primitive lock objects.

A primitive lock is a synchronization primitive that is not owned
by a particular coroutine when locked.  A primitive lock is in one
of two states, 'locked' or 'unlocked'.

It is created in the unlocked state.  It has two basic methods,
acquire() and release().  When the state is unlocked, acquire()
changes the state to locked and returns immediately.  When the
state is locked, acquire() blocks until a call to release() in
another coroutine changes it to unlocked, then the acquire() call
resets it to locked and returns.  The release() method should only
be called in the locked state; it changes the state to unlocked
and returns immediately.  If an attempt is made to release an
unlocked lock, a RuntimeError will be raised.

When more than one coroutine is blocked in acquire() waiting for
the state to turn to unlocked, only one coroutine proceeds when a
release() call resets the state to unlocked; first coroutine which
is blocked in acquire() is being processed.

acquire() is a coroutine and should be called with 'await'.

Locks also support the asynchronous context management protocol.
'async with lock' statement should be used.

Usage:

    lock = Lock()
    ...
    await lock.acquire()
    try:
        ...
    finally:
        lock.release()

Context manager usage:

    lock = Lock()
    ...
    async with lock:
         ...

Lock objects can be tested for locking state:

    if not lock.locked():
       await lock.acquire()
    else:
       # lock is acquired
       ...

### método `Lock.acquire(self)`

Acquire a lock.

This method blocks until the lock is unlocked, then sets it to
locked and returns True.

### método `Lock.locked(self)`

Return True if lock is acquired.

### método `Lock.release(self)`

Release a lock.

When the lock is locked, reset it to unlocked, and return.
If any other coroutines are blocked waiting for the lock to become
unlocked, allow exactly one of them to proceed.

When invoked on an unlocked lock, a RuntimeError is raised.

There is no return value.

## clase `asyncio.locks.Event()`

Asynchronous equivalent to threading.Event.

Class implementing event objects. An event manages a flag that can be set
to true with the set() method and reset to false with the clear() method.
The wait() method blocks until the flag is true. The flag is initially
false.

### método `Event.clear(self)`

Reset the internal flag to false. Subsequently, coroutines calling
wait() will block until set() is called to set the internal flag
to true again.

### método `Event.is_set(self)`

Return True if and only if the internal flag is true.

### método `Event.set(self)`

Set the internal flag to true. All coroutines waiting for it to
become true are awakened. Coroutine that call wait() once the flag is
true will not block at all.

### método `Event.wait(self)`

Block until the internal flag is true.

If the internal flag is true on entry, return True
immediately.  Otherwise, block until another coroutine calls
set() to set the flag to true, then return True.

## clase `asyncio.locks.Condition(lock=None)`

Asynchronous equivalent to threading.Condition.

This class implements condition variable objects. A condition variable
allows one or more coroutines to wait until they are notified by another
coroutine.

A new Lock object is created and used as the underlying lock.

### método `Condition.notify(self, n=1)`

By default, wake up one coroutine waiting on this condition, if any.
If the calling coroutine has not acquired the lock when this method
is called, a RuntimeError is raised.

This method wakes up at most n of the coroutines waiting for the
condition variable; it is a no-op if no coroutines are waiting.

Note: an awakened coroutine does not actually return from its
wait() call until it can reacquire the lock. Since notify() does
not release the lock, its caller should.

### método `Condition.notify_all(self)`

Wake up all threads waiting on this condition. This method acts
like notify(), but wakes up all waiting threads instead of one. If the
calling thread has not acquired the lock when this method is called,
a RuntimeError is raised.

### método `Condition.wait(self)`

Wait until notified.

If the calling coroutine has not acquired the lock when this
method is called, a RuntimeError is raised.

This method releases the underlying lock, and then blocks
until it is awakened by a notify() or notify_all() call for
the same condition variable in another coroutine.  Once
awakened, it re-acquires the lock and returns True.

### método `Condition.wait_for(self, predicate)`

Wait until a predicate becomes true.

The predicate should be a callable which result will be
interpreted as a boolean value.  The final predicate value is
the return value.

## clase `asyncio.locks.Semaphore(value=1)`

A Semaphore implementation.

A semaphore manages an internal counter which is decremented by each
acquire() call and incremented by each release() call. The counter
can never go below zero; when acquire() finds that it is zero, it blocks,
waiting until some other thread calls release().

Semaphores also support the context management protocol.

The optional argument gives the initial value for the internal
counter; it defaults to 1. If the value given is less than 0,
ValueError is raised.

### método `Semaphore.acquire(self)`

Acquire a semaphore.

If the internal counter is larger than zero on entry,
decrement it by one and return True immediately.  If it is
zero on entry, block, waiting until some other coroutine has
called release() to make it larger than 0, and then return
True.

### método `Semaphore.locked(self)`

Returns True if semaphore cannot be acquired immediately.

### método `Semaphore.release(self)`

Release a semaphore, incrementing the internal counter by one.

When it was zero on entry and another coroutine is waiting for it to
become larger than zero again, wake up that coroutine.

## clase `asyncio.locks.BoundedSemaphore(value=1)`

A bounded semaphore implementation.

This raises ValueError in release() if it would increase the value
above the initial value.

### método `BoundedSemaphore.release(self)`

Release a semaphore, incrementing the internal counter by one.

When it was zero on entry and another coroutine is waiting for it to
become larger than zero again, wake up that coroutine.

## clase `asyncio.locks.Barrier(parties)`

Asyncio equivalent to threading.Barrier

Implements a Barrier primitive.
Useful for synchronizing a fixed number of tasks at known synchronization
points. Tasks block on 'wait()' and are simultaneously awoken once they
have all made their call.

### método `Barrier.abort(self)`

Place the barrier into a 'broken' state.

Useful in case of error.  Any currently waiting tasks and tasks
attempting to 'wait()' will have BrokenBarrierError raised.

### método `Barrier.reset(self)`

Reset the barrier to the initial state.

Any tasks currently waiting will get the BrokenBarrier exception
raised.

### método `Barrier.wait(self)`

Wait for the barrier.

When the specified number of tasks have started waiting, they are all
simultaneously awoken.
Returns an unique and individual index number from 0 to 'parties-1'.
