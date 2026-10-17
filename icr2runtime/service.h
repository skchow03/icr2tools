#pragma once

// Read-only by default. --enable-data-writes permits guarded DATA patching.
void runReadOnlyService(bool enableWrites, bool enableCodeWrites = false);
