---
categoria: utilidades
etiquetas: dataclass, field, clases
---
# Módulo `dataclasses`



## función `dataclasses.dataclass(cls=None, /, *, init=True, repr=True, eq=True, order=False, unsafe_hash=False, frozen=False, match_args=True, kw_only=False, slots=False, weakref_slot=False)`

Add dunder methods based on the fields defined in the class.

Examines PEP 526 __annotations__ to determine fields.

If init is true, an __init__() method is added to the class. If repr
is true, a __repr__() method is added. If order is true, rich
comparison dunder methods are added. If unsafe_hash is true, a
__hash__() method is added. If frozen is true, fields may not be
assigned to after instance creation. If match_args is true, the
__match_args__ tuple is added. If kw_only is true, then by default
all fields are keyword-only. If slots is true, a new class with a
__slots__ attribute is returned.

## función `dataclasses.field(*, default=<dataclasses._MISSING_TYPE object at 0x0000013F345439B0>, default_factory=<dataclasses._MISSING_TYPE object at 0x0000013F345439B0>, init=True, repr=True, hash=None, compare=True, metadata=None, kw_only=<dataclasses._MISSING_TYPE object at 0x0000013F345439B0>)`

Return an object to identify dataclass fields.

default is the default value of the field.  default_factory is a
0-argument function called to initialize a field's value.  If init
is true, the field will be a parameter to the class's __init__()
function.  If repr is true, the field will be included in the
object's repr().  If hash is true, the field will be included in the
object's hash().  If compare is true, the field will be used in
comparison functions.  metadata, if specified, must be a mapping
which is stored but not otherwise examined by dataclass.  If kw_only
is true, the field will become a keyword-only parameter to
__init__().

It is an error to specify both default and default_factory.

## clase `dataclasses.FrozenInstanceError(...)`

Attribute not found.

## función `dataclasses.fields(class_or_instance)`

Return a tuple describing the fields of this dataclass.

Accepts a dataclass or an instance of one. Tuple elements are of
type Field.

## función `dataclasses.asdict(obj, *, dict_factory=<class 'dict'>)`

Return the fields of a dataclass instance as a new dictionary mapping
field names to field values.

Example usage::

  @dataclass
  class C:
      x: int
      y: int

  c = C(1, 2)
  assert asdict(c) == {'x': 1, 'y': 2}

If given, 'dict_factory' will be used instead of built-in dict.
The function applies recursively to field values that are
dataclass instances. This will also look into built-in containers:
tuples, lists, and dicts. Other objects are copied with 'copy.deepcopy()'.

## función `dataclasses.astuple(obj, *, tuple_factory=<class 'tuple'>)`

Return the fields of a dataclass instance as a new tuple of field values.

Example usage::

  @dataclass
  class C:
      x: int
      y: int

  c = C(1, 2)
  assert astuple(c) == (1, 2)

If given, 'tuple_factory' will be used instead of built-in tuple.
The function applies recursively to field values that are
dataclass instances. This will also look into built-in containers:
tuples, lists, and dicts. Other objects are copied with 'copy.deepcopy()'.

## función `dataclasses.make_dataclass(cls_name, fields, *, bases=(), namespace=None, init=True, repr=True, eq=True, order=False, unsafe_hash=False, frozen=False, match_args=True, kw_only=False, slots=False, weakref_slot=False, module=None)`

Return a new dynamically created dataclass.

The dataclass name will be 'cls_name'.  'fields' is an iterable
of either (name), (name, type) or (name, type, Field) objects. If type is
omitted, use the string 'typing.Any'.  Field objects are created by
the equivalent of calling 'field(name, type [, Field-info])'.::

  C = make_dataclass('C', ['x', ('y', int), ('z', int, field(init=False))], bases=(Base,))

is equivalent to::

  @dataclass
  class C(Base):
      x: 'typing.Any'
      y: int
      z: int = field(init=False)

For the bases and namespace parameters, see the builtin type() function.

The parameters init, repr, eq, order, unsafe_hash, frozen, match_args, kw_only,
slots, and weakref_slot are passed to dataclass().

If module parameter is defined, the '__module__' attribute of the dataclass is
set to that value.

## función `dataclasses.replace(obj, /, **changes)`

Return a new object replacing specified fields with new values.

This is especially useful for frozen classes.  Example usage::

  @dataclass(frozen=True)
  class C:
      x: int
      y: int

  c = C(1, 2)
  c1 = replace(c, x=3)
  assert c1.x == 3 and c1.y == 2

## función `dataclasses.is_dataclass(obj)`

Returns True if obj is a dataclass or an instance of a
dataclass.
