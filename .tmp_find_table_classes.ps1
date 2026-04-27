Get-ChildItem -Path electron/src/renderer -Recurse -File -Include *.jsx,*.mjs |
  Select-String -Pattern 'profiles-table-wrap|table-wrap|scrollable-with-fade|scrollable' -CaseSensitive:$false |
  ForEach-Object { "{0}:{1}: {2}" -f $_.Path,$_.LineNumber,$_.Line.Trim() }
