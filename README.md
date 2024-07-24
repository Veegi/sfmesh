# SFMesh
SFMesh is a file format designed for compatibility with Starfall's mesh utilities.

SFMesh files are designed to be included as SF source code, in order to leverage the built-in file upload system for distributing the data to clients. As such the standard file extension is `.txt`. For use in other systems a binary format may be used, with the extension `.sfmesh`.

## Format Version `1.0` Specification

Text-based SFMesh files are Starfall modules and should be loaded like any other module. SFMesh files must return a Base64 encoded string representing the FastLZ-compressed binary mesh data as the first returned value. The alternative binary format foregoes the Base64 conversion, but is still compressed.

The FastLZ compression method is defined by the SF / GLua implementation, which is non-standard; it requires the length of the uncompressed data to be inserted near the beginning of the compressed string (in little-endian form). The following Python snippet is a functioning example:
```python
lzc_string = lzma.compress(buffer_value, format=lzma.FORMAT_ALONE, preset=9)
lzc_string = lzc_string[:5] + uncompressed_size.to_bytes(8, 'little') + lzc_string[13:]
```

The binary data format is described below in BNF form.
All values are written in the little-endian byte order.

```bnf
<SFMesh> ::= <header> <data>
```

### Header

```bnf
<header> ::= <version> <options> <objects-header>
```

#### Version

```bnf
<version> ::= <major> <minor> <type>
<major> ::= uint8
<minor> ::= uint8
<type> ::= uint8
```

The version number consists of the major, minor, and type fields. Major and minor denote the semantic version number.
A parser should be backwards compatible with any file with the same major version, given that no incompatible options are set.

The type field is used for denoting release candidates / development versions of the format which do not follow any released specification.

#### Options

```bnf
<options> ::= uint32
```

The options field is used to store option flags.
No options have been defined as of yet.

#### Objects Header

```bnf
<objects-header> ::= <num-objects> {<object-metadata>}
<num-objects> ::= uint32
```

The Objects Header contains the number of objects in the file, followed by the metadata of each object consecutively.

```bnf
<object-metadata> ::= <name-length> <name> <triangle-count>
<name-length> ::= uint32
<name> ::= string
<triangle-count> ::= uint16
```

The individual object's metadata contains the object's name, encoded using a variable length, and the triangle count.
The maximum triangle count is 2^16-1, as set by the engine.

### Data

The data section consists of all the vertices of the objects in the file. It is possible to skip and read only the desired objects from the data section using the information found in the header; explicit offsets are _not_ included to conserve space.

```bnf
<data> ::= {<triangle>}
<triangle> ::= <vertex> <vertex> <vertex>
<vertex> ::= <position> <normal> <uv> <tangent>

<position> ::= float32 float32 float32
<normal> ::= float32 float32 float32
<uv> ::= float32 float32
<tangent> ::= float32 float32 float32
```
