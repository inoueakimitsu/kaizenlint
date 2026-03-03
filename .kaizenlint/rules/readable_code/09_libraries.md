---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# ライブラリとシンプルさ

## ライブラリの機能を活用してコードを簡潔にする

言語やフレームワークの豊富なメソッドやAPIを活用し、複雑な自作ロジックを避けます。ライブラリが提供する高レベルAPIを使うことで、不要なコード記述を避けられます。ただし、コード内またはドキュメントで意図的にライブラリを使用しない設計判断が記述されている場合 (例: 依存関係の最小化、ポータビリティの確保) は、このルールの適用を除外してください。

**Bad:**
```javascript
var show_next_tip = function () {
  var num_tips = $('.tip').size();
  var shown_tip = $('.tip:visible');
  var shown_tip_num = Number(shown_tip.attr('id').slice(4));
  if (shown_tip_num === num_tips) {
    $('#tip-1').show();
  } else {
    $('#tip-' + (shown_tip_num + 1)).show();
  }
  shown_tip.hide();
};
```

**Good:**
```javascript
var show_next_tip = function () {
  var cur_tip = $('.tip:visible').hide();
  var next_tip = cur_tip.next('.tip');
  if (next_tip.size() === 0) {
    next_tip = $('.tip:first');
  }
  next_tip.show();
};
```

## 標準ライブラリを定期的に学習する

標準ライブラリの関数やモジュールの名前を定期的 (15 分程度) に読み直し、適切なツールを活用します。自前実装より標準ライブラリを使います。

**Bad:**
```cpp
// 重複排除を自前実装
std::vector<int> unique(std::vector<int>& elements) {
    std::map<int, bool> seen;
    std::vector<int> result;
    for (int e : elements) {
        if (seen.find(e) == seen.end()) {
            result.push_back(e);
            seen[e] = true;
        }
    }
    return result;
}
```

**Good:**
```cpp
// 標準ライブラリを使用
std::set<int> unique_set(elements.begin(), elements.end());
std::vector<int> result(unique_set.begin(), unique_set.end());
```

## 未使用のコードを削除する

実装した機能が使用されていない場合、定期的に削除します。コードを書く時間投資を恐れて未使用コードを保持すべきではありません。

**Bad:**
```python
def handle_international_filenames(path):
    """国際的なファイル名を処理 (実装されたが使われていない)"""
    pass

def recover_from_memory_shortage():
    """メモリ不足からの回復ロジック (実装されたが使われない)"""
    pass
```

**Good:**
```python
# 実際に使用される機能のみを実装
def handle_common_filenames(path):
    pass
```
