---
categoria: estructuras_de_datos
etiquetas: deque, counter, defaultdict, namedtuple
---
# Módulo `collections`

This module implements specialized container datatypes providing
alternatives to Python's general purpose built-in containers, dict,
list, set, and tuple.

* namedtuple   factory function for creating tuple subclasses with named fields
* deque        list-like container with fast appends and pops on either end
* ChainMap     dict-like class for creating a single view of multiple mappings
* Counter      dict subclass for counting hashable objects
* OrderedDict  dict subclass that remembers the order entries were added
* defaultdict  dict subclass that calls a factory function to supply missing values
* UserDict     wrapper around dictionary objects for easier dict subclassing
* UserList     wrapper around list objects for easier list subclassing
* UserString   wrapper around string objects for easier string subclassing

## clase `collections.ChainMap(*maps)`

A ChainMap groups multiple dicts (or other mappings) together
to create a single, updateable view.

The underlying mappings are stored in a list.  That list is public and can
be accessed or updated using the *maps* attribute.  There is no other
state.

Lookups search the underlying mappings successively until a key is found.
In contrast, writes, updates, and deletions only operate on the first
mapping.

### método `ChainMap.clear(self)`

Clear maps[0], leaving maps[1:] intact.

### método `ChainMap.copy(self)`

New ChainMap or subclass with a new copy of maps[0] and refs to maps[1:]

### método `ChainMap.get(self, key, default=None)`

D.get(k[,d]) -> D[k] if k in D, else d.  d defaults to None.

### método `ChainMap.new_child(self, m=None, **kwargs)`

New ChainMap with a new map followed by all previous maps.
If no map is provided, an empty dict is used.
Keyword arguments update the map or new empty dict.

### método `ChainMap.pop(self, key, *args)`

Remove *key* from maps[0] and return its value. Raise KeyError if *key* not in maps[0].

### método `ChainMap.popitem(self)`

Remove and return an item pair from maps[0]. Raise KeyError is maps[0] is empty.

## clase `collections.Counter(iterable=None, /, **kwds)`

Dict subclass for counting hashable items.  Sometimes called a bag
or multiset.  Elements are stored as dictionary keys and their counts
are stored as dictionary values.

>>> c = Counter('abcdeabcdabcaba')  # count elements from a string

>>> c.most_common(3)                # three most common elements
[('a', 5), ('b', 4), ('c', 3)]
>>> sorted(c)                       # list all unique elements
['a', 'b', 'c', 'd', 'e']
>>> ''.join(sorted(c.elements()))   # list elements with repetitions
'aaaaabbbbcccdde'
>>> sum(c.values())                 # total of all counts
15

>>> c['a']                          # count of letter 'a'
5
>>> for elem in 'shazam':           # update counts from an iterable
...     c[elem] += 1                # by adding 1 to each element's count
>>> c['a']                          # now there are seven 'a'
7
>>> del c['b']                      # remove all 'b'
>>> c['b']                          # now there are zero 'b'
0

>>> d = Counter('simsalabim')       # make another counter
>>> c.update(d)                     # add in the second counter
>>> c['a']                          # now there are nine 'a'
9

>>> c.clear()                       # empty the counter
>>> c
Counter()

Note:  If a count is set to zero or reduced to zero, it will remain
in the counter until the entry is deleted or the counter is cleared:

>>> c = Counter('aaabbc')
>>> c['b'] -= 2                     # reduce the count of 'b' by two
>>> c.most_common()                 # 'b' is still in, but its count is zero
[('a', 3), ('c', 1), ('b', 0)]

### método `Counter.copy(self)`

Return a shallow copy.

### método `Counter.elements(self)`

Iterator over elements repeating each as many times as its count.

>>> c = Counter('ABCABC')
>>> sorted(c.elements())
['A', 'A', 'B', 'B', 'C', 'C']

Knuth's example for prime factors of 1836:  2**2 * 3**3 * 17**1

>>> import math
>>> prime_factors = Counter({2: 2, 3: 3, 17: 1})
>>> math.prod(prime_factors.elements())
1836

Note, if an element's count has been set to zero or is a negative
number, elements() will ignore it.

### método `Counter.most_common(self, n=None)`

List the n most common elements and their counts from the most
common to the least.  If n is None, then list all element counts.

>>> Counter('abracadabra').most_common(3)
[('a', 5), ('b', 2), ('r', 2)]

### método `Counter.subtract(self, iterable=None, /, **kwds)`

Like dict.update() but subtracts counts instead of replacing them.
Counts can be reduced below zero.  Both the inputs and outputs are
allowed to contain zero and negative counts.

Source can be an iterable, a dictionary, or another Counter instance.

>>> c = Counter('which')
>>> c.subtract('witch')             # subtract elements from another iterable
>>> c.subtract(Counter('watch'))    # subtract elements from another counter
>>> c['h']                          # 2 in which, minus 1 in witch, minus 1 in watch
0
>>> c['w']                          # 1 in which, minus 1 in witch, minus 1 in watch
-1

### método `Counter.total(self)`

Sum of the counts

### método `Counter.update(self, iterable=None, /, **kwds)`

Like dict.update() but add counts instead of replacing them.

Source can be an iterable, a dictionary, or another Counter instance.

>>> c = Counter('which')
>>> c.update('witch')           # add elements from another iterable
>>> d = Counter('watch')
>>> c.update(d)                 # add elements from another counter
>>> c['h']                      # four 'h' in which, witch, and watch
4

## clase `collections.OrderedDict(...)`

Dictionary that remembers insertion order

## clase `collections.UserDict(dict=None, /, **kwargs)`

A MutableMapping is a generic container for associating
key/value pairs.

This class provides concrete generic implementations of all
methods except for __getitem__, __setitem__, __delitem__,
__iter__, and __len__.

### método `UserDict.get(self, key, default=None)`

D.get(k[,d]) -> D[k] if k in D, else d.  d defaults to None.

## clase `collections.UserList(initlist=None)`

A more or less complete user-defined wrapper around list objects.

### método `UserList.append(self, item)`

S.append(value) -- append value to the end of the sequence

### método `UserList.clear(self)`

S.clear() -> None -- remove all items from S

### método `UserList.count(self, item)`

S.count(value) -> integer -- return number of occurrences of value

### método `UserList.extend(self, other)`

S.extend(iterable) -- extend sequence by appending elements from the iterable

### método `UserList.index(self, item, *args)`

S.index(value, [start, [stop]]) -> integer -- return first index of value.
Raises ValueError if the value is not present.

Supporting start and stop arguments is optional, but
recommended.

### método `UserList.insert(self, i, item)`

S.insert(index, value) -- insert value before index

### método `UserList.pop(self, i=-1)`

S.pop([index]) -> item -- remove and return item at index (default last).
Raise IndexError if list is empty or index is out of range.

### método `UserList.remove(self, item)`

S.remove(value) -- remove first occurrence of value.
Raise ValueError if the value is not present.

### método `UserList.reverse(self)`

S.reverse() -- reverse *IN PLACE*

## clase `collections.UserString(seq)`

All the operations on a read-only sequence.

Concrete subclasses must override __new__ or __init__,
__getitem__, and __len__.

### método `UserString.count(self, sub, start=0, end=9223372036854775807)`

S.count(value) -> integer -- return number of occurrences of value

### método `UserString.index(self, sub, start=0, end=9223372036854775807)`

S.index(value, [start, [stop]]) -> integer -- return first index of value.
Raises ValueError if the value is not present.

Supporting start and stop arguments is optional, but
recommended.

## clase `collections.defaultdict(...)`

defaultdict(default_factory=None, /, [...]) --> dict with default factory

The default factory is called without arguments to produce
a new value when a key is not present, in __getitem__ only.
A defaultdict compares equal to a dict with the same items.
All remaining arguments are treated the same as if they were
passed to the dict constructor, including keyword arguments.

## clase `collections.deque(...)`

deque([iterable[, maxlen]]) --> deque object

A list-like sequence optimized for data accesses near its endpoints.

## función `collections.namedtuple(typename, field_names, *, rename=False, defaults=None, module=None)`

Returns a new subclass of tuple with named fields.

>>> Point = namedtuple('Point', ['x', 'y'])
>>> Point.__doc__                   # docstring for the new class
'Point(x, y)'
>>> p = Point(11, y=22)             # instantiate with positional args or keywords
>>> p[0] + p[1]                     # indexable like a plain tuple
33
>>> x, y = p                        # unpack like a regular tuple
>>> x, y
(11, 22)
>>> p.x + p.y                       # fields also accessible by name
33
>>> d = p._asdict()                 # convert to a dictionary
>>> d['x']
11
>>> Point(**d)                      # convert from a dictionary
Point(x=11, y=22)
>>> p._replace(x=100)               # _replace() is like str.replace() but targets named fields
Point(x=100, y=22)
