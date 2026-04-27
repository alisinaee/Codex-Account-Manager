Get-ChildItem -Path electron/src -Recurse -File -Include *.js,*.jsx,*.mjs |
  Select-String -Pattern 'remaining percentage|usage.*(<=|>=|<|>)|buildStatusTone\(|usageColor\(|usageTone\(|usageBandForPercent|usageCssColorVar|usageHexColor|windows.*tone' -CaseSensitive:$false |
  ForEach-Object { "{0}:{1}: {2}" -f $_.Path,$_.LineNumber,$_.Line.Trim() }
