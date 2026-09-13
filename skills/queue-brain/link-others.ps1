$targets = @(
  'C:\Users\neoop\.gemini\skills\queue-brain',
  'C:\Users\neoop\.cursor\skills\queue-brain',
  'C:\Users\neoop\.cursor\skills-cursor\queue-brain',
  'C:\Users\neoop\.codex\skills\queue-brain'
)
foreach ($p in $targets) {
  $j = New-Item -ItemType Junction -Path $p -Target 'C:\Users\neoop\.agents\skills\queue-brain'
  Write-Output ("{0} -> {1}" -f $j.FullName, $j.LinkType)
}
