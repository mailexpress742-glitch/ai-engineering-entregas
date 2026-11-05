---
categoria: estructuras_de_datos
etiquetas: cache, partial, reduce, decoradores
---
# Módulo `functools`

functools.py - Tools for working with functions and callable objects

## función `functools.update_wrapper(wrapper, wrapped, assigned=('__module__', '__name__', '__qualname__', '__doc__', '__annotations__', '__type_params__'), updated=('__dict__',))`

Update a wrapper function to look like the wrapped function

wrapper is the function to be updated
wrapped is the original function
assigned is a tuple naming the attributes assigned directly
from the wrapped function to the wrapper function (defaults to
functools.WRAPPER_ASSIGNMENTS)
updated is a tuple naming the attributes of the wrapper that
are updated with the corresponding attribute from the wrapped
function (defaults to functools.WRAPPER_UPDATES)

## función `functools.wraps(wrapped, assigned=('__module__', '__name__', '__qualname__', '__doc__', '__annotations__', '__type_params__'), updated=('__dict__',))`

Decorator factory to apply update_wrapper() to a wrapper function

Returns a decorator that invokes update_wrapper() with the decorated
function as the wrapper argument and the arguments to wraps() as the
remaining arguments. Default arguments are as for update_wrapper().
This is a convenience function to simplify applying partial() to
update_wrapper().

## función `functools.total_ordering(cls)`

Class decorator that fills in missing ordering methods

## función `functools.cache(user_function, /)`

Simple lightweight unbounded cache.  Sometimes called "memoize".

## función `functools.lru_cache(maxsize=128, typed=False)`

Least-recently-used cache decorator.

If *maxsize* is set to None, the LRU features are disabled and the cache
can grow without bound.

If *typed* is True, arguments of different types will be cached separately.
For example, f(3.0) and f(3) will be treated as distinct calls with
distinct results.

Arguments to the cached function must be hashable.

View the cache statistics named tuple (hits, misses, maxsize, currsize)
with f.cache_info().  Clear the cache and statistics with f.cache_clear().
Access the underlying function with f.__wrapped__.

See:  https://en.wikipedia.org/wiki/Cache_replacement_policies#Least_recently_used_(LRU)

## clase `functools.partial(...)`

partial(func, *args, **keywords) - new function with partial application
of the given arguments and keywords.

## clase `functools.partialmethod(func, /, *args, **keywords)`

Method descriptor with partial application of the given arguments
and keywords.

Supports wrapping existing descriptors and handles non-descriptor
callables as instance methods.

## función `functools.singledispatch(func)`

Single-dispatch generic function decorator.

Transforms a function into a generic function, which can have different
behaviours depending upon the type of its first argument. The decorated
function acts as the default implementation, and additional
implementations can be registered using the register() attribute of the
generic function.

## clase `functools.singledispatchmethod(func)`

Single-dispatch generic method descriptor.

Supports wrapping existing descriptors and handles non-descriptor
callables as instance methods.

### método `singledispatchmethod.register(self, cls, method=None)`

generic_method.register(cls, func) -> func

Registers a new implementation for the given *cls* on a *generic_method*.
