# Chinese Metadata Role Mappings

When Excel metadata files use Chinese column headers, map only the metadata
role labels before parsing. Business field names should be preserved by default
and only sanitized into valid Python identifiers.

## Standard Mappings

```python
CHINESE_COLUMN_MAP = {
    # Field name
    "字段名": "field_name",
    "字段名称": "field_name",
    "列名": "field_name",
    "属性名": "field_name",
    "英文字段名": "field_name",
    "源字段": "field_name",
    "字段英文名": "field_name",

    # Data type
    "数据类型": "data_type",
    "字段类型": "data_type",
    "类型": "data_type",

    # Length / precision
    "长度": "length",
    "字段长度": "length",
    "精度": "precision",

    # Constraint
    "约束": "constraint",
    "约束条件": "constraint",
    "是否主键": "is_primary_key",
    "主键": "is_primary_key",
    "是否非空": "is_not_null",
    "非空": "is_not_null",
    "是否唯一": "is_unique",
    "唯一": "is_unique",

    # Default value
    "默认值": "default_value",

    # Description
    "描述": "description",
    "备注": "description",
    "说明": "description",
    "字段说明": "description",
    "注释": "description",

    # Table name
    "表名": "table_name",
    "表名称": "table_name",
    "英文表名": "table_name",

    # Chinese name
    "中文名": "chinese_name",
    "字段中文名": "chinese_name",
    "中文字段名": "chinese_name",

    # Reference / FK
    "关联表": "reference_table",
    "外键关联": "reference_table",
    "关联字段": "reference_field",
    "外键": "is_foreign_key",
}

def normalize_columns(df):
    """Normalize metadata role columns such as 字段名/说明/数据类型."""
    return df.rename(columns=CHINESE_COLUMN_MAP)
```

---

## Common Chinese Data Type Values

```python
CHINESE_TYPE_MAP = {
    "字符串": "varchar",
    "整数": "int",
    "浮点数": "float",
    "小数": "decimal",
    "布尔": "boolean",
    "日期": "date",
    "时间": "time",
    "日期时间": "datetime",
    "时间戳": "timestamp",
    "文本": "text",
    "长文本": "text",
    "JSON": "json",
    "二进制": "binary",
    "枚举": "enum",
}
```

---

## Common True/False Values in Chinese Excel

```python
TRUTHY_VALUES = {"是", "Y", "YES", "TRUE", "1", "✓", "√", "有"}
FALSY_VALUES  = {"否", "N", "NO", "FALSE", "0", "", "无", None}

def is_truthy(val) -> bool:
    if val is None:
        return False
    return str(val).strip().upper() in {v.upper() for v in TRUTHY_VALUES}
```

---

## Table Name Detection

Sheet names are often the table name. Clean them:

```python
import re

def sheet_to_table_name(sheet_name: str) -> str:
    """Convert sheet name to a valid Python class name and SQL table name."""
    # Remove leading numbers/dots: "1.用户表" → "用户表"
    name = re.sub(r'^\d+[\.\、\s]*', '', sheet_name.strip())
    # Preserve Chinese or mixed-language names; only replace invalid separators.
    return re.sub(r'\W+', '_', name).strip('_') or 'table'

def to_class_name(table_name: str) -> str:
    """Convert snake_case table name to PascalCase class name."""
    return ''.join(word.capitalize() for word in table_name.split('_'))
```
