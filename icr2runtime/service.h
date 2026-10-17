#pragma once

// Read-only by default. --enable-data-writes permits guarded DATA patching.
// idleTimeoutSeconds=0 disables automatic shutdown; 60 is suitable for
// automatically launched services whose clients use persistent sessions.
void runReadOnlyService(bool enableWrites, bool enableCodeWrites = false,
                        unsigned idleTimeoutSeconds = 0);
