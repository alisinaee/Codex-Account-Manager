$path='electron/scripts/dev.js'
$lines=Get-Content $path
for($i=1;$i -le $lines.Length;$i++){"{0}: {1}" -f $i,$lines[$i-1]}
