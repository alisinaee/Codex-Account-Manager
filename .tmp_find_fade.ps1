Get-ChildItem -Path electron/src/styles -Recurse -File -Include *.css |
  Select-String -Pattern 'fade|gradient|mask|profiles-table|table-wrap|::after|::before|overflow' -CaseSensitive:$false |
  ForEach-Object { "{0}:{1}: {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim() }
