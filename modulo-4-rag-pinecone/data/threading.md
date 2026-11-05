---
categoria: concurrencia
etiquetas: hilos, locks, threads
---
# Módulo `threading`

Thread module emulating a subset of Java's threading model.

## función `threading.active_count()`

Return the number of Thread objects currently alive.

The returned count is equal to the length of the list returned by
enumerate().

## clase `threading.Condition(lock=None)`

Class that implements a condition variable.

A condition variable allows one or more threads to wait until they are
notified by another thread.

If the lock argument is given and not None, it must be a Lock or RLock
object, and it is used as the underlying lock. Otherwise, a new RLock object
is created and used as the underlying lock.

### método `Condition.notify(self, n=1)`

Wake up one or more threads waiting on this condition, if any.

If the calling thread has not acquired the lock when this method is
called, a RuntimeError is raised.

This method wakes up at most n of the threads waiting for the condition
variable; it is a no-op if no threads are waiting.

### método `Condition.notifyAll(self)`

Wake up all threads waiting on this condition.

This method is deprecated, use notify_all() instead.

### método `Condition.notify_all(self)`

Wake up all threads waiting on this condition.

If the calling thread has not acquired the lock when this method
is called, a RuntimeError is raised.

### método `Condition.wait(self, timeout=None)`

Wait until notified or until a timeout occurs.

If the calling thread has not acquired the lock when this method is
called, a RuntimeError is raised.

This method releases the underlying lock, and then blocks until it is
awakened by a notify() or notify_all() call for the same condition
variable in another thread, or until the optional timeout occurs. Once
awakened or timed out, it re-acquires the lock and returns.

When the timeout argument is present and not None, it should be a
floating-point number specifying a timeout for the operation in seconds
(or fractions thereof).

When the underlying lock is an RLock, it is not released using its
release() method, since this may not actually unlock the lock when it
was acquired multiple times recursively. Instead, an internal interface
of the RLock class is used, which really unlocks it even when it has
been recursively acquired several times. Another internal interface is
then used to restore the recursion level when the lock is reacquired.

### método `Condition.wait_for(self, predicate, timeout=None)`

Wait until a condition evaluates to True.

predicate should be a callable which result will be interpreted as a
boolean value.  A timeout may be provided giving the maximum time to
wait.

## función `threading.current_thread()`

Return the current Thread object, corresponding to the caller's thread of control.

If the caller's thread of control was not created through the threading
module, a dummy thread object with limited functionality is returned.

## función `threading.enumerate()`

Return a list of all Thread objects currently alive.

The list includes daemonic threads, dummy thread objects created by
current_thread(), and the main thread. It excludes terminated threads and
threads that have not yet been started.

## función `threading.main_thread()`

Return the main thread object.

In normal conditions, the main thread is the thread from which the
Python interpreter was started.

## clase `threading.Event()`

Class implementing event objects.

Events manage a flag that can be set to true with the set() method and reset
to false with the clear() method. The wait() method blocks until the flag is
true.  The flag is initially false.

### método `Event.clear(self)`

Reset the internal flag to false.

Subsequently, threads calling wait() will block until set() is called to
set the internal flag to true again.

### método `Event.isSet(self)`

Return true if and only if the internal flag is true.

This method is deprecated, use is_set() instead.

### método `Event.is_set(self)`

Return true if and only if the internal flag is true.

### método `Event.set(self)`

Set the internal flag to true.

All threads waiting for it to become true are awakened. Threads
that call wait() once the flag is true will not block at all.

### método `Event.wait(self, timeout=None)`

Block until the internal flag is true.

If the internal flag is true on entry, return immediately. Otherwise,
block until another thread calls set() to set the flag to true, or until
the optional timeout occurs.

When the timeout argument is present and not None, it should be a
floating-point number specifying a timeout for the operation in seconds
(or fractions thereof).

This method returns the internal flag on exit, so it will always return
True except if a timeout is given and the operation times out.

## función `threading.RLock(*args, **kwargs)`

Factory function that returns a new reentrant lock.

A reentrant lock must be released by the thread that acquired it. Once a
thread has acquired a reentrant lock, the same thread may acquire it again
without blocking; the thread must release it once for each time it has
acquired it.

## clase `threading.Semaphore(value=1)`

This class implements semaphore objects.

Semaphores manage a counter representing the number of release() calls minus
the number of acquire() calls, plus an initial value. The acquire() method
blocks if necessary until it can return without making the counter
negative. If not given, value defaults to 1.

### método `Semaphore.acquire(self, blocking=True, timeout=None)`

Acquire a semaphore, decrementing the internal counter by one.

When invoked without arguments: if the internal counter is larger than
zero on entry, decrement it by one and return immediately. If it is zero
on entry, block, waiting until some other thread has called release() to
make it larger than zero. This is done with proper interlocking so that
if multiple acquire() calls are blocked, release() will wake exactly one
of them up. The implementation may pick one at random, so the order in
which blocked threads are awakened should not be relied on. There is no
return value in this case.

When invoked with blocking set to true, do the same thing as when called
without arguments, and return true.

When invoked with blocking set to false, do not block. If a call without
an argument would block, return false immediately; otherwise, do the
same thing as when called without arguments, and return true.

When invoked with a timeout other than None, it will block for at
most timeout seconds.  If acquire does not complete successfully in
that interval, return false.  Return true otherwise.

### método `Semaphore.release(self, n=1)`

Release a semaphore, incrementing the internal counter by one or more.

When the counter is zero on entry and another thread is waiting for it
to become larger than zero again, wake up that thread.

## clase `threading.BoundedSemaphore(value=1)`

Implements a bounded semaphore.

A bounded semaphore checks to make sure its current value doesn't exceed its
initial value. If it does, ValueError is raised. In most situations
semaphores are used to guard resources with limited capacity.

If the semaphore is released too many times it's a sign of a bug. If not
given, value defaults to 1.

Like regular semaphores, bounded semaphores manage a counter representing
the number of release() calls minus the number of acquire() calls, plus an
initial value. The acquire() method blocks if necessary until it can return
without making the counter negative. If not given, value defaults to 1.

### método `BoundedSemaphore.release(self, n=1)`

Release a semaphore, incrementing the internal counter by one or more.

When the counter is zero on entry and another thread is waiting for it
to become larger than zero again, wake up that thread.

If the number of releases exceeds the number of acquires,
raise a ValueError.

## clase `threading.Thread(group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None)`

A class that represents a thread of control.

This class can be safely subclassed in a limited fashion. There are two ways
to specify the activity: by passing a callable object to the constructor, or
by overriding the run() method in a subclass.

### método `Thread.getName(self)`

Return a string used for identification purposes only.

This method is deprecated, use the name attribute instead.

### método `Thread.isDaemon(self)`

Return whether this thread is a daemon.

This method is deprecated, use the daemon attribute instead.

### método `Thread.is_alive(self)`

Return whether the thread is alive.

This method returns True just before the run() method starts until just
after the run() method terminates. See also the module function
enumerate().

### método `Thread.join(self, timeout=None)`

Wait until the thread terminates.

This blocks the calling thread until the thread whose join() method is
called terminates -- either normally or through an unhandled exception
or until the optional timeout occurs.

When the timeout argument is present and not None, it should be a
floating-point number specifying a timeout for the operation in seconds
(or fractions thereof). As join() always returns None, you must call
is_alive() after join() to decide whether a timeout happened -- if the
thread is still alive, the join() call timed out.

When the timeout argument is not present or None, the operation will
block until the thread terminates.

A thread can be join()ed many times.

join() raises a RuntimeError if an attempt is made to join the current
thread as that would cause a deadlock. It is also an error to join() a
thread before it has been started and attempts to do so raises the same
exception.

### método `Thread.run(self)`

Method representing the thread's activity.

You may override this method in a subclass. The standard run() method
invokes the callable object passed to the object's constructor as the
target argument, if any, with sequential and keyword arguments taken
from the args and kwargs arguments, respectively.

### método `Thread.setDaemon(self, daemonic)`

Set whether this thread is a daemon.

This method is deprecated, use the .daemon property instead.

### método `Thread.setName(self, name)`

Set the name string for this thread.

This method is deprecated, use the name attribute instead.

### método `Thread.start(self)`

Start the thread's activity.

It must be called at most once per thread object. It arranges for the
object's run() method to be invoked in a separate thread of control.

This method will raise a RuntimeError if called more than once on the
same thread object.

## clase `threading.Barrier(parties, action=None, timeout=None)`

Implements a Barrier.

Useful for synchronizing a fixed number of threads at known synchronization
points.  Threads block on 'wait()' and are simultaneously awoken once they
have all made that call.

### método `Barrier.abort(self)`

Place the barrier into a 'broken' state.

Useful in case of error.  Any currently waiting threads and threads
attempting to 'wait()' will have BrokenBarrierError raised.

### método `Barrier.reset(self)`

Reset the barrier to the initial state.

Any threads currently waiting will get the BrokenBarrier exception
raised.

### método `Barrier.wait(self, timeout=None)`

Wait for the barrier.

When the specified number of threads have started waiting, they are all
simultaneously awoken. If an 'action' was provided for the barrier, one
of the threads will have executed that callback prior to returning.
Returns an individual index number from 0 to 'parties-1'.

## clase `threading.BrokenBarrierError(...)`

Unspecified run-time error.

## clase `threading.Timer(interval, function, args=None, kwargs=None)`

Call a function after a specified number of seconds:

t = Timer(30.0, f, args=None, kwargs=None)
t.start()
t.cancel()     # stop the timer's action if it's still waiting

### método `Timer.cancel(self)`

Stop the timer if it hasn't finished yet.

### método `Timer.run(self)`

Method representing the thread's activity.

You may override this method in a subclass. The standard run() method
invokes the callable object passed to the object's constructor as the
target argument, if any, with sequential and keyword arguments taken
from the args and kwargs arguments, respectively.

## función `threading.setprofile(func)`

Set a profile function for all threads started from the threading module.

The func will be passed to sys.setprofile() for each thread, before its
run() method is called.

## función `threading.settrace(func)`

Set a trace function for all threads started from the threading module.

The func will be passed to sys.settrace() for each thread, before its run()
method is called.

## función `threading.gettrace()`

Get the trace function as set by threading.settrace().

## función `threading.getprofile()`

Get the profiler function as set by threading.setprofile().

## función `threading.setprofile_all_threads(func)`

Set a profile function for all threads started from the threading module
and all Python threads that are currently executing.

The func will be passed to sys.setprofile() for each thread, before its
run() method is called.

## función `threading.settrace_all_threads(func)`

Set a trace function for all threads started from the threading module
and all Python threads that are currently executing.

The func will be passed to sys.settrace() for each thread, before its run()
method is called.
