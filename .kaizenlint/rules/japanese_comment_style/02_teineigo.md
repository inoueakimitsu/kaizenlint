---
applies_to: ["*.py", "*.md", "*.txt", "*.rst", "*.sh", "*.yml", "*.yaml", "*.toml", "*.conf", "*.cfg", "*.ini", "*.js", "*.ts", "*.tsx", "*.jsx", "*.java", "*.rb", "*.go", "*.c", "*.cpp", "*.cxx", "*.rs", "*.cs", "*.kt", "*.swift"]
---
## 丁寧語の使用

コメントや docstring は丁寧語で書いてください。「～をする」は「～をします。」のようにしてください。ただし、docstring のセクション見出し (Parameters、Returns、Raises、Notes、Examples 等) は NumPy 形式の固定キーワードであるため、英語のまま記述してください。これらはツール互換性のために必要であり、丁寧語の対象外です。

**Bad:**
```python
# ～の選択を行う
```

**Good:**
```python
# ～の選択を行います。
```
