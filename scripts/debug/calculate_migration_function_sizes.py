#!/usr/bin/env python3
"""Calculate function sizes in migrations.py"""

functions = [
    (21, "_safe_execute_sql"),
    (47, "_table_exists"),
    (61, "_column_exists"),
    (80, "_is_generated_column"),
    (112, "begin_connection"),
    (118, "_get_schema_version"),
    (130, "_set_schema_version"),
    (139, "apply_migrations"),
    (218, "_upgrade_to_v2"),
    (241, "_upgrade_to_v3"),
    (259, "_upgrade_to_v4"),
    (284, "_upgrade_to_v6"),
    (322, "_upgrade_to_v5"),
    (410, "_upgrade_to_v7"),
    (679, "_upgrade_to_v8"),
    (758, "_upgrade_to_v9"),
    (1006, "_upgrade_to_v10"),
    (1250, "_upgrade_to_v11"),
    (1608, "_upgrade_to_v12"),
    (1717, "_upgrade_to_v13"),
    (1823, "_upgrade_to_v14"),
    (1892, "_downgrade_from_v9"),
]

# Calculate sizes
results = []
for i in range(len(functions) - 1):
    start, name = functions[i]
    end = functions[i + 1][0] - 1
    size = end - start + 1
    results.append((size, name, start, end))

# Last function - estimate to end of file (~1950 lines based on typical migration files)
start, name = functions[-1]
size = 50  # Conservative estimate
results.append((size, name, start, start + size))

# Sort by size descending
results.sort(reverse=True)

print("## migrations.py Function Analysis\n")
print("| Size | Function | Lines | Priority |")
print("|------|----------|-------|----------|")

priority1 = []
priority2 = []
skip = []

for size, name, start, end in results:
    if size >= 80:
        priority = "PRIORITY 1"
        priority1.append((size, name, start, end))
    elif size >= 60:
        priority = "PRIORITY 2"
        priority2.append((size, name, start, end))
    else:
        priority = "SKIP (<60)"
        skip.append((size, name, start, end))

    print(f"| {size} | `{name}` | {start}-{end} | {priority} |")

print(f"\n**PRIORITY 1 (>80 lines)**: {len(priority1)} functions")
print(f"**PRIORITY 2 (60-80 lines)**: {len(priority2)} functions")
print(f"**SKIP (<60 lines)**: {len(skip)} functions")

print("\n## Testing Strategy")
print(f"\n### Morning: Test PRIORITY 1 ({len(priority1)} functions)")
for size, name, start, end in priority1[:6]:
    print(f"- `{name}` ({size} lines) - lines {start}-{end}")

print(f"\n### Afternoon: Test PRIORITY 2 ({len(priority2)} functions)")
for size, name, start, end in priority2[:6]:
    print(f"- `{name}` ({size} lines) - lines {start}-{end}")
