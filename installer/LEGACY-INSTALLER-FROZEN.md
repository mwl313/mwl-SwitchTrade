# Legacy installer freeze

The PowerShell installer under this directory is retained only for migration fixtures, regression
tests, and historical recovery analysis. It cannot produce a release or unsigned private-beta
package after the `legacy-installer-20260827` tag.

All new packages must be built from
`installer/replacement/Build-ReplacementPackage.ps1`. The replacement pipeline owns the immutable
WSL appliance, native provisioner, per-user MSI, and compressed WiX Burn bundle.
