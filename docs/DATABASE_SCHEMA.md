# KOPDES Database Schema

## Tables

### `connection_profiles`

- `id`: UUID-style string primary key
- `name`: unique profile name
- `description`: operator notes
- `protocol`: transport type
- `server_address`: hostname or IP
- `port`: integer
- `username`: username or account identifier
- `encrypted_password`: encrypted credential blob
- `route_metric`: preferred route priority
- `dns_servers`: comma-separated DNS list
- `mtu`: interface MTU
- `keepalive`: keepalive interval
- `auto_reconnect`: boolean
- `allow_multiple`: boolean
- `tags`: many-to-many via `profile_tags`
- `config_payload`: imported config snapshot
- `created_at`, `updated_at`

### `route_policies`

- `id`
- `profile_id`
- `mode`: default, split, full, policy
- `table_name`
- `metric`
- `source_cidr`
- `destination_cidr`
- `gateway`
- `priority`
- `is_failover`
- `created_at`, `updated_at`

### `health_checks`

- `id`
- `profile_id`
- `check_type`: ping, tcp, http, dns
- `target`
- `interval_seconds`
- `timeout_seconds`
- `failure_threshold`
- `recovery_threshold`
- `enabled`

### `connection_sessions`

- `id`
- `profile_id`
- `status`
- `started_at`
- `ended_at`
- `latency_ms`
- `packet_loss`
- `jitter_ms`
- `bytes_in`
- `bytes_out`
- `reconnect_count`
- `last_error`
- `local_ip`
- `remote_ip`

### `event_logs`

- `id`
- `profile_id`
- `level`
- `event_type`
- `message`
- `details`
- `created_at`

### `tags`

- `id`
- `name`

### `profile_tags`

- `profile_id`
- `tag_id`

## Indexes

- unique index on `connection_profiles.name`
- index on `connection_sessions.status`
- index on `event_logs.created_at`
- index on `health_checks.profile_id`
- index on `route_policies.profile_id`

## Secrets

Sensitive data is stored as encrypted text using an application-managed key. The encryption key is not stored in the database.
