---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# コードレビューとコミット

## 小さな diff で commit する

変更を commit する際、diff だけを読んでも読みやすいコードになっているか判断できるように、コード変更を小分けにして commit します。1 つの diff に 1 つの変更を含めます。各改善方法ごとに別々にコミットすることで、diff の目的が明確になり、レビュアーが変更の意図を理解しやすくなります。

**Bad:**
```
git add file1.py file2.py file3.py
git commit -m "Improve code readability"
# 3つのファイルで異なる改善を同時に行っている
```

**Good:**
```
git add file1.py
git commit -m "Use clearer variable names in fetch_data()"

git add file2.py
git commit -m "Align vertical lines in data structures"
```

