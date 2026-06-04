# Parsing Notes

## Supported Python Class Styles

The ontology parser supports multiple Python class definition patterns commonly used in data modeling:

### 1. Dataclass

```python
from dataclasses import dataclass

@dataclass
class Person:
    """A human individual."""
    name: str
    age: int = 0
    email: str = None
```

**Parsing strategy:**
- Decorator: `@dataclass`
- Fields: extracted from `AnnAssign` nodes (annotated assignments)
- Default values: captured from assignment value
- Comments: inline comments after field definition

### 2. Pydantic BaseModel

```python
from pydantic import BaseModel, Field

class Person(BaseModel):
    """A human individual."""
    name: str
    age: int = Field(default=0, description="Age in years")
    email: str = Field(default=None, description="Contact email")
```

**Parsing strategy:**
- Base class: `BaseModel`
- Fields: extracted from `AnnAssign` nodes
- Field descriptions: captured from `Field(description=...)` if present
- Default values: captured from `Field(default=...)`

### 3. Plain Annotated Class

```python
class Person:
    """A human individual."""
    name: str
    age: int
    email: str  # Contact email
```

**Parsing strategy:**
- No decorator or special base
- Fields: extracted from `AnnAssign` nodes
- Comments: inline comments captured
- No default values (unless explicitly assigned)

### 4. Class with `__init__`

```python
class Person:
    """A human individual."""
    
    def __init__(self, name: str, age: int, email: str = None):
        self.name = name
        self.age = age
        self.email = email
```

**Parsing strategy:**
- Fields: extracted from `__init__` method parameters (excluding `self`)
- Type annotations: from parameter annotations
- Default values: from parameter defaults
- **Limitation**: Cannot capture inline comments for individual fields

### 5. Mixed Styles

Some classes may mix annotated fields with `__init__`:

```python
class Person:
    """A human individual."""
    name: str  # Full name
    age: int
    
    def __init__(self, name: str, age: int, email: str = None):
        self.name = name
        self.age = age
        self.email = email
```

**Parsing strategy:**
- Collect both annotated fields AND `__init__` parameters
- Deduplicate by field name (prefer annotated version for comments)

## AST Parsing Details

### Field Extraction

The parser uses Python's `ast` module to walk the class body:

```python
for item in node.body:
    if isinstance(item, ast.AnnAssign):
        # Annotated field: name: type = default
        field = parse_annotated_field(item)
    elif isinstance(item, ast.FunctionDef) and item.name == "__init__":
        # Extract from __init__ parameters
        fields = parse_init_method(item)
```

### Type Annotation Handling

Type annotations are converted to strings using `ast.unparse()`:

```python
age: int                    → "int"
name: Optional[str]         → "Optional[str]"
items: List[Dict[str, Any]] → "List[Dict[str, Any]]"
```

### Comment Extraction

Inline comments are extracted by reading the source line:

```python
name: str  # Full name
```

The parser:
1. Gets the line number from the AST node
2. Reads the corresponding source line
3. Splits on `#` and captures the comment part
4. Filters out type comments (`# type: ...`)

### Default Value Handling

Default values are captured as strings:

```python
age: int = 0                → default: "0"
name: str = "Unknown"       → default: '"Unknown"'
items: List = []            → default: "[]"
config: Dict = Field(...)   → default: "Field(...)"
```

## Edge Cases

### 1. Circular Imports

If ontology files have circular imports, the parser may fail. Solution:
- Parse files individually without executing imports
- Only analyze class definitions, not runtime behavior

### 2. Dynamic Class Generation

Classes created dynamically (e.g., via `type()` or metaclasses) cannot be parsed:

```python
Person = type('Person', (object,), {'name': str, 'age': int})
```

**Limitation**: Only statically defined classes are supported.

### 3. Nested Classes

Nested class definitions are captured but may need special handling:

```python
class Outer:
    class Inner:
        field: str
```

**Current behavior**: Both `Outer` and `Inner` are extracted as separate classes.

### 4. Property Decorators

Properties are not treated as fields:

```python
class Person:
    _name: str
    
    @property
    def name(self) -> str:
        return self._name
```

**Parsing**: Only `_name` is captured as a field, not `name` property.

### 5. Class Variables vs Instance Variables

The parser treats all annotated attributes as fields:

```python
class Person:
    species: str = "Homo sapiens"  # Class variable
    name: str                       # Instance variable
```

**Parsing**: Both are captured as fields. Distinguishing class vs instance variables requires runtime analysis.

### 6. Forward References

String-based forward references are preserved:

```python
class Person:
    manager: "Person"  # Forward reference
```

**Parsing**: Type is captured as `"Person"` (string literal).

### 7. Union Types

Union types are preserved as-is:

```python
from typing import Union

class Person:
    age: Union[int, str]  # Could be int or str
```

**Parsing**: Type is `"Union[int, str]"`.

## Error Handling

### Syntax Errors

If a file has syntax errors, parsing fails immediately:

```python
class Person
    name: str  # Missing colon
```

**Behavior**: Raise `ValueError` with syntax error details, stop processing.

### Encoding Issues

Files must be UTF-8 encoded. If encoding fails:

**Behavior**: Raise `ValueError` with encoding error details.

### Missing Files

If a specified file doesn't exist:

**Behavior**: Raise `FileNotFoundError`.

## Performance Considerations

- **Large files**: AST parsing is fast, but very large files (>10K lines) may take a few seconds
- **Many files**: Parsing is done sequentially; for 100+ files, consider parallel processing
- **Memory**: Each parsed class is kept in memory as a JSON object; for thousands of classes, memory usage may be significant

## Testing Strategy

To test the parser:

1. Create sample ontology files with various styles
2. Run parser and verify JSON output
3. Check field extraction, type annotations, comments, defaults
4. Test edge cases (nested classes, forward references, etc.)
