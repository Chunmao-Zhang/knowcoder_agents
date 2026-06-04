# Semantic Alignment Prompt Template

You are helping to merge Python ontology class definitions from multiple sources. Your task is to identify which classes represent the same real-world concept, even if they have different names.

## Input Format

You will receive a list of class definitions with:
- Class name
- Docstring (if available)
- Field names and types
- Source file

## Your Task

Analyze the classes and group together those that represent the same conceptual entity. Consider:

1. **Semantic equivalence**: Do the classes describe the same real-world object?
   - Example: "Person" and "Human" likely refer to the same concept
   - Example: "用户" (user), "客户" (customer), and "会员" (member) might be the same in one case but distinct in another
   - Example: "Vehicle" and "Car" are related but NOT the same (Car is more specific)

2. **Field overlap**: Do they share similar fields?
   - High field overlap suggests they're the same concept
   - But be careful: "User" and "Admin" might share fields but be different concepts

3. **Domain context**: Consider the uploaded case context, workbook labels, and user question
   - "用户" (user), "客户" (customer), and "会员" (member) may align only when the case semantics support it
   - Product, plan, subscription, SKU, or service labels may be related but should stay distinct unless fields and context show equivalence

4. **Inheritance relationships**: If one class inherits from another, they're usually NOT the same
   - Example: If "Admin" extends "User", keep them separate

## Output Format

Return a JSON array of arrays, where each inner array contains class names that should be merged:

```json
[
  ["Person", "Human", "人"],
  ["Vehicle", "交通工具"],
  ["TelecomUser", "订户", "Subscriber"]
]
```

## Important Rules

- **When in doubt, keep separate**: Only group classes if you're confident they're the same concept
- **Preserve specificity**: Don't merge a general class with a specific subtype
- **Consider context**: Use docstrings and field names to understand intent
- **Single classes**: If a class has no semantic match, omit it from the output (it will pass through unchanged)

## Example

Input:
```
Classes to align:

1. Person
   Docstring: "Represents a human individual"
   Fields: name (str), age (int), email (str)
   Source: domain_ontology.py

2. Human
   Docstring: "A human being in the system"
   Fields: full_name (str), birth_year (int), contact_email (str)
   Source: user_ontology.py

3. Employee
   Docstring: "An employee of the company"
   Fields: name (str), employee_id (str), department (str)
   Source: hr_ontology.py

4. Vehicle
   Docstring: "A motorized transport"
   Fields: make (str), model (str), year (int)
   Source: transport_ontology.py
```

Output:
```json
[
  ["Person", "Human"]
]
```

Reasoning:
- Person and Human are clearly the same concept (human individual)
- Employee is more specific (a type of person with employment relationship) - keep separate
- Vehicle is completely different - keep separate

---

## Actual Input

{CLASS_LIST}

Please analyze and return the JSON array of merge groups.
