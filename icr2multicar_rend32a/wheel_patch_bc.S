.intel_syntax noprefix
.code32
.section .text
.global hook_main
.global hook_direct

/* Both entry points are reached via the game's existing near calls to 0x47690.
   Preserve its side-effects, then write only to the actually attached chassis. */
hook_main:
    call 0x47690
    pushfd
    pushad
    mov ecx, dword ptr [esp+0x3c]
    test ecx, ecx
    jz main_invalid
    mov ecx, dword ptr [ecx]
    test ecx, ecx
    jz main_invalid
    mov ecx, dword ptr [ecx+0x74]
    jmp main_ready
main_invalid:
    mov ecx, -1
main_ready:
    mov eax, dword ptr [esp+8]   /* saved EBP = wheel phase */
    mov ebx, dword ptr [esp+0x64] /* original stack +0x3C = steering */
    xor edx, edx
    call update_wheels
    popad
    popfd
    ret

.org 0x50, 0x90
hook_direct:
    call 0x47690
    pushfd
    pushad
    mov ecx, dword ptr [edi+0x74]
    mov eax, dword ptr [esi+0x24]
    mov ebx, dword ptr [esi+0x28]
    mov edx, 1
    call update_wheels
    popad
    popfd
    ret

update_wheels:
    call get_base
get_base:
    pop ebp
    lea ebp, [ebp+trace_buffer-get_base]
    inc dword ptr [ebp+8+edx*4]
    mov dword ptr [ebp+44],ecx  /* last car index examined */
    cmp ecx, 32
    ja invalid
    /* slot table relocation obtained from existing loader-relocated instruction */
    mov esi, dword ptr [ebp+0x44c9e-0xab6e0]
    mov esi, dword ptr [esi+ecx*4]
    test esi,esi
    jz invalid
    mov esi, dword ptr [esi]  /* F16 root */
    test esi,esi
    jz invalid
    cmp dword ptr [esi], 0x10
    jne invalid
    cmp dword ptr [esi+8], 4
    jb invalid
    push edx       /* stream id   [esp+8] */
    push eax       /* phase       [esp+4] */
    push ebx       /* steering    [esp] */
    mov edx, esi   /* root */
    /* Exclude the two original chassis by comparing true loaded F16 roots.
       Read already-relocated addresses from original mov eax,[imm32] instructions. */
    mov eax, dword ptr [ebp+0x14950-0xab6e0]
    mov eax, dword ptr [eax]
    test eax,eax
    jz test_indycar
    mov eax, dword ptr [eax]
    cmp eax,edx
    je legacy_stack
 test_indycar:
    mov eax, dword ptr [ebp+0x1496b-0xab6e0]
    mov eax, dword ptr [eax]
    test eax,eax
    jz validate_start
    mov eax, dword ptr [eax]
    cmp eax,edx
    je legacy_stack
validate_start:
    xor edi,edi
validation_loop:
    mov esi, dword ptr [edx+0x0c+edi*4]
    test esi,esi
    jz invalid_stack
    cmp dword ptr [esi], 0x0f
    jne invalid_stack
    inc edi
    cmp edi,4
    jb validation_loop

.ifdef SINGLE
    mov eax, dword ptr [ebp+0x20]
    cmp eax, -1
    jne single_check
    /* Choose first eligible nonselected car; report that index. */
    mov dword ptr [ebp+0x20],ecx
    jmp write_wheels
single_check:
    cmp eax,ecx
    jne skipped_stack
.endif
write_wheels:
    mov dword ptr [ebp+0x28],edx /* last valid root */
    mov dword ptr [ebp+0x24],ecx /* last success index */
    xor edi,edi
write_loop:
    mov esi, dword ptr [edx+0x0c+edi*4]
    cmp edi,2
    jb front_resource
    mov eax, dword ptr [ebp+0x476c3-0xab6e0]
    jmp resource_ready
front_resource:
    mov eax, dword ptr [ebp+0x476b1-0xab6e0]
resource_ready:
    mov eax,dword ptr [eax]
    mov eax,dword ptr [eax]
    mov dword ptr [esi+0x1c],eax
    xor eax,eax
    cmp edi,2
    jae rear_rotation
    mov eax,dword ptr [esp]
rear_rotation:
    test edi,1
    jz z_ready
    xor eax,0x80000000
z_ready:
    mov dword ptr [esi+0x10],eax
    mov eax,dword ptr [esp+4]
    test edi,1
    jz y_ready
    neg eax
y_ready:
    mov dword ptr [esi+0x14],eax
    mov dword ptr [esi+0x18],0
    inc edi
    cmp edi,4
    jb write_loop
    mov edx,dword ptr [esp+8]
    inc dword ptr [ebp+16+edx*4]
    jmp cleanup_stack
skipped_stack:
    /* Not counted as a failed pointer; this is the single-car filter. */
    jmp cleanup_stack
legacy_stack:
    mov eax,dword ptr [esp+8]
    inc dword ptr [ebp+48+eax*4]
    jmp cleanup_stack
invalid_stack:
    mov eax,dword ptr [esp+8]
    inc dword ptr [ebp+24+eax*4]
cleanup_stack:
    add esp,12
    ret
invalid:
    inc dword ptr [ebp+24+edx*4]
    ret

.org 0x350,0x90
trace_buffer:
    .ascii "ICW2"
    .long 2
    .long 0,0       /* hit counters */
    .long 0,0       /* update counters */
    .long 0,0       /* invalid pointer counts */
    .long -1        /* single-car target index; -1 until latched */
    .long -1        /* last updated car index */
    .long 0         /* last updated chassis root */
    .long -1        /* most recent car index */
    .long 0,0       /* original roadcar / indycar skipped */
