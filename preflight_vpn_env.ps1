param()

$ErrorActionPreference = "Stop"

function Find-PreferredIPv4 {
    $wifi = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Беспроводная сеть" -ErrorAction SilentlyContinue `
        | Where-Object { $_.PrefixOrigin -ne "WellKnown" } `
        | Select-Object -First 1 -ExpandProperty IPAddress
    if ($wifi) {
        return $wifi
    }

    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue `
        | Where-Object {
            $_.IPAddress -notmatch '^127\.' -and
            $_.IPAddress -notmatch '^169\.254\.' -and
            $_.InterfaceAlias -notmatch 'outline|tap|vpn|loopback|virtual|bluetooth'
        } `
        | Select-Object -ExpandProperty IPAddress -Unique
    return ($candidates | Select-Object -First 1)
}

$ip = Find-PreferredIPv4
if ($ip) {
    $env:BITRIX24_SOURCE_IP = $ip
    $env:VIBECODE_SOURCE_IP = $ip
}

$result = [ordered]@{
    ok = [bool]$ip
    source_ip = $ip
    has_bitrix_webhook = [bool](-not [string]::IsNullOrWhiteSpace($env:BITRIX24_WEBHOOK))
    has_vibecode_api_key = [bool](-not [string]::IsNullOrWhiteSpace($env:VIBECODE_API_KEY))
    timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
}

$result | ConvertTo-Json -Depth 5
