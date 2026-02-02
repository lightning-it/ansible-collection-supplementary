## [1.14.1](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.14.0...v1.14.1) (2026-02-02)

### Bug Fixes

* format galaxy.yml for consistency and readability ([#65](https://github.com/lightning-it/ansible-collection-supplementary/issues/65)) ([ab4a030](https://github.com/lightning-it/ansible-collection-supplementary/commit/ab4a030cfab48af7d3ea90ad14777cd8428031be))

## [1.14.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.13.0...v1.14.0) (2026-02-02)

### Features

* add host network support and improve SELinux handling for Vault and CoreDNS deployments ([6e7fd14](https://github.com/lightning-it/ansible-collection-supplementary/commit/6e7fd14c4e95b92adac656b50bb2a95c17bf666f))
* Add roles for managing Kea Podman deployment, including configuration, deployment, operations, and validation ([#54](https://github.com/lightning-it/ansible-collection-supplementary/issues/54)) ([372794e](https://github.com/lightning-it/ansible-collection-supplementary/commit/372794e4f53bb7c1fc701d41a7898bccca90a029))
* enhance CoreDNS and Vault deployment with resolver management and health checks ([5cb64a6](https://github.com/lightning-it/ansible-collection-supplementary/commit/5cb64a6300a3a38601bee59cf052f534ceac41bf))
* Implement MinIO bootstrap role with configuration, migration, and verification tasks ([43a6181](https://github.com/lightning-it/ansible-collection-supplementary/commit/43a618101dcfdbd619d1840e6777d12cce2b32c7))

### Bug Fixes

* always wait for API health ([8b9f035](https://github.com/lightning-it/ansible-collection-supplementary/commit/8b9f03568443d94ebb69790592c14dccd1baf102))
* cleanup ([a1b6316](https://github.com/lightning-it/ansible-collection-supplementary/commit/a1b63162ac6086bc65bb65f3fb6a2efc5470ccd7))
* do not run when selinux is disabled ([aebcb1b](https://github.com/lightning-it/ansible-collection-supplementary/commit/aebcb1b32e2ca0b5542f56b600b7881d4d7167c6))
* fix certificate handling ([94216e8](https://github.com/lightning-it/ansible-collection-supplementary/commit/94216e81583727b6bfee7375ae5e7d13be949a55))
* kubeplay is not working ([2f22f61](https://github.com/lightning-it/ansible-collection-supplementary/commit/2f22f61e5c78fbb2062c6870904fde4bbd267fcd))
* remove lit.foundational.kubeplay calls ([a7238d8](https://github.com/lightning-it/ansible-collection-supplementary/commit/a7238d8233bd5c5f7b179edf3438a4135d75ba6e))
* use ansible_os_family ([d394c31](https://github.com/lightning-it/ansible-collection-supplementary/commit/d394c31c84d12a64c9ab9453c6a3d1b616e3621e))

## [1.13.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.12.0...v1.13.0) (2026-01-25)

### Features

* Add MinIO roles for bootstrap, configuration, deployment, operations, and validation ([#50](https://github.com/lightning-it/ansible-collection-supplementary/issues/50)) ([07aa415](https://github.com/lightning-it/ansible-collection-supplementary/commit/07aa415dce0842f68836300919812650c01d2df1))

## [1.12.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.11.0...v1.12.0) (2026-01-25)

### Features

* ansible role nexus reactored ([#49](https://github.com/lightning-it/ansible-collection-supplementary/issues/49)) ([225b966](https://github.com/lightning-it/ansible-collection-supplementary/commit/225b966b747695b5e50960d55ef375690fc31c56))

## [1.11.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.10.0...v1.11.0) (2026-01-22)

### Features

* ansible role vault refactored ([#48](https://github.com/lightning-it/ansible-collection-supplementary/issues/48)) ([102f515](https://github.com/lightning-it/ansible-collection-supplementary/commit/102f51539a1352999246e1e469da2aaaad25ecb3))

## [1.10.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.9.0...v1.10.0) (2026-01-19)

### Features

* new ansible role vault ([#47](https://github.com/lightning-it/ansible-collection-supplementary/issues/47)) ([43b25c4](https://github.com/lightning-it/ansible-collection-supplementary/commit/43b25c4bec8fbdf0eafb3dee7ca62cbffa6ae4cf))

## [1.9.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.8.0...v1.9.0) (2026-01-19)

### Features

* new nexus role ([#44](https://github.com/lightning-it/ansible-collection-supplementary/issues/44)) ([4d408f1](https://github.com/lightning-it/ansible-collection-supplementary/commit/4d408f1897d598f56fb4938cd28f22f88aefac8a))

## [1.8.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.7.0...v1.8.0) (2026-01-17)

### Features

* add aap_deploy role with basic functionality and documentation ([#45](https://github.com/lightning-it/ansible-collection-supplementary/issues/45)) ([c627319](https://github.com/lightning-it/ansible-collection-supplementary/commit/c627319269791cb537588af88b5cc4f0299ee695))

## [1.7.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.6.1...v1.7.0) (2026-01-16)

### Features

* add cloudflared role for managing Cloudflare Tunnel connectors ([#42](https://github.com/lightning-it/ansible-collection-supplementary/issues/42)) ([f97e997](https://github.com/lightning-it/ansible-collection-supplementary/commit/f97e997ec6f3b878b386e0c9d8f37616dab49690))

## [1.6.1](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.6.0...v1.6.1) (2026-01-16)

### Bug Fixes

* ansible role vault consolidation ([#40](https://github.com/lightning-it/ansible-collection-supplementary/issues/40)) ([5cea882](https://github.com/lightning-it/ansible-collection-supplementary/commit/5cea882f4488def73e38664a110afedcdb567b6e))

## [1.6.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.5.2...v1.6.0) (2026-01-14)

### Features

* add cloudflared role for managing Cloudflare Tunnel connectors ([#41](https://github.com/lightning-it/ansible-collection-supplementary/issues/41)) ([366f797](https://github.com/lightning-it/ansible-collection-supplementary/commit/366f79768fa85ac853668739e06f91aad3694db7))

## [1.5.2](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.5.1...v1.5.2) (2026-01-07)

### Bug Fixes

* ensure no_log is set for user management task in manage_esxi role ([#39](https://github.com/lightning-it/ansible-collection-supplementary/issues/39)) ([23f2980](https://github.com/lightning-it/ansible-collection-supplementary/commit/23f29803418c4dd36144ca5104ddf74f73214983))

## [1.5.1](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.5.0...v1.5.1) (2026-01-07)

### Bug Fixes

* format galaxy.yml for improved readability and consistency ([#38](https://github.com/lightning-it/ansible-collection-supplementary/issues/38)) ([3c5c2ca](https://github.com/lightning-it/ansible-collection-supplementary/commit/3c5c2ca3f27e5d5b39965c41dc77290c2c441546))

## [1.5.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.4.3...v1.5.0) (2026-01-07)

### Features

* enhance manage_esxi role with additional variables and tasks fo… ([#32](https://github.com/lightning-it/ansible-collection-supplementary/issues/32)) ([63e01be](https://github.com/lightning-it/ansible-collection-supplementary/commit/63e01be66b3dc94032e495e49e567635314924a7))

## [1.4.3](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.4.2...v1.4.3) (2026-01-04)

### Bug Fixes

* sync shared assets from lightning-it/shared-assets ([#29](https://github.com/lightning-it/ansible-collection-supplementary/issues/29)) ([878f29e](https://github.com/lightning-it/ansible-collection-supplementary/commit/878f29e32d5363baadd6ec140fcf05da8c510ad5))

## [1.4.2](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.4.1...v1.4.2) (2026-01-04)

### Bug Fixes

* update environment variable name from ANSIBLE_COLLECTIONS_PATHS to ANSIBLE_COLLECTIONS_PATH ([#30](https://github.com/lightning-it/ansible-collection-supplementary/issues/30)) ([36d1104](https://github.com/lightning-it/ansible-collection-supplementary/commit/36d1104f25bf776e6715a07bb5230302794f1e29))

## [1.4.1](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.4.0...v1.4.1) (2025-12-31)

### Bug Fixes

* update Ansible roles to use Terragrunt and enhance manage_esxi role configuration ([#21](https://github.com/lightning-it/ansible-collection-supplementary/issues/21)) ([f9df604](https://github.com/lightning-it/ansible-collection-supplementary/commit/f9df6040577c11aec7d18fb0f22afbd033ce3fcf))

## [1.4.0](https://github.com/lightning-it/ansible-collection-supplementary/compare/v1.3.0...v1.4.0) (2025-12-30)

### Features

* new ansible roles ([#17](https://github.com/lightning-it/ansible-collection-supplementary/issues/17)) ([ed9cd84](https://github.com/lightning-it/ansible-collection-supplementary/commit/ed9cd842396983e37eba88ad6c4d0edd8dbc96e3))

## 1.3.0 (2025-12-22)

* feat: Add new roles (#8) ([75fe60e](https://github.com/lightning-it/ansible-collection-supplementary/commit/75fe60e)), closes [#8](https://github.com/lightning-it/ansible-collection-supplementary/issues/8)

## 1.2.0 (2025-12-19)

* feat: Add @semantic-release/exec dependency to package.json and package-lock.json (#7) ([da170fc](https://github.com/lightning-it/ansible-collection-supplementary/commit/da170fc)), closes [#7](https://github.com/lightning-it/ansible-collection-supplementary/issues/7)
* feat: Add CI workflows for collection linting, testing, and publishing ([4beb108](https://github.com/lightning-it/ansible-collection-supplementary/commit/4beb108))
* fix: Update script permissions for bump_galaxy_version.py (#6) ([f222380](https://github.com/lightning-it/ansible-collection-supplementary/commit/f222380)), closes [#6](https://github.com/lightning-it/ansible-collection-supplementary/issues/6)

## 1.1.0 (2025-12-17)

* feat: Add workflow to publish collection to Ansible Galaxy (#4) ([32699a5](https://github.com/lightning-it/ansible-collection-supplementary/commit/32699a5)), closes [#4](https://github.com/lightning-it/ansible-collection-supplementary/issues/4)

## 1.0.0 (2025-12-17)

* feat: Add Keycloak role and Terraform integration ([4d86a42](https://github.com/lightning-it/ansible-collection-supplementary/commit/4d86a42))
* feat: Add Keycloak role and Terraform integration ([4994ce1](https://github.com/lightning-it/ansible-collection-supplementary/commit/4994ce1))
* feat: Add Keycloak role and Terraform integration ([d8c3454](https://github.com/lightning-it/ansible-collection-supplementary/commit/d8c3454))
* Initial commit ([4d8687b](https://github.com/lightning-it/ansible-collection-supplementary/commit/4d8687b))
