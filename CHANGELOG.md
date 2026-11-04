# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Calculated Fahrenheit dew point for Ecobee thermostat climate sensors.
- Raw Celsius/Fahrenheit conversion helpers alongside the rounded conversion helpers.

### Changed
- Migrated ThermoWorks to the read-only Cloud v1 devices API, using the API key from the existing 1Password item's password field.

## [1.0.0] - 2026-04-30

### Added
- Multi-source weather data aggregation (Ecobee, Davis, Honeywell, SensorPush, ThermoWorks)
- RESTful API endpoints for weather data retrieval
- Health check endpoint for container orchestration
- Comprehensive test suite (49+ unit tests)
- Docker containerization with health checks
- Docker Compose configuration for easy deployment
- GitHub Actions CI/CD workflows
- Security policy and vulnerability reporting
- Detailed API documentation
- Environment-based configuration
- 1Password integration for credential management

### Changed
- Improved startup script with better error handling
- Enhanced logging configuration
- Optimized Docker build with multi-layer caching
- Updated GitHub workflows with coverage reporting

### Fixed
- Logging configuration compatibility issues
- File path issues for cross-platform support
- Exception handling in station modules
- Test coverage and assertions

### Security
- Added security policy documentation
- Implemented Docker health checks
- Removed hardcoded paths and credentials
- Updated to Python 3.13 for security patches
- Added SECURITY.md with best practices

### Deprecated
- Legacy Windows syslog stub (no longer needed)

## Style Guide

### Versions
Versions follow Semantic Versioning (MAJOR.MINOR.PATCH):
- MAJOR: Incompatible API changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes

### Notable Versions
- **Latest**: 1.0.0
- **Stable**: 1.0.0
