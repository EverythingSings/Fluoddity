// GLSL Lock-Free Concurrent Free List Stack
// Buffer layout
layout(std430, binding = 1) restrict buffer FreeListBuffer {
    uint head;             // Atomic counter: number of items in stack
    uint buffer_data[];    // Stack storage for available IDs
};

// Configuration constants
const uint BUFFER_SIZE = ENTITY_COUNT +64;// 64;  // Slightly larger than max entities
const uint INVALID_ID = 0xFFFFFFFF;         // Returned when stack is empty

// Push an ID onto the stack
// Always succeeds since stack is sized to hold all entities
void free_list_push(uint id) {
    // Atomically increment head and get the index to store at
    uint index = atomicAdd(head, 1);
    
    // Store the ID at the reserved position
    buffer_data[index] = id;
}

// Pop an ID from the stack
// Returns the ID on success, INVALID_ID if stack is empty
uint free_list_pop() {
    // Pre-check: avoid atomic operation if stack is clearly empty
    if (head == 0||head>BUFFER_SIZE*2) {
        return INVALID_ID;
    }
    
    // Atomically decrement head to reserve an item
    uint old_head = atomicAdd(head, -1);
    
    // Check if stack was actually empty when we decremented
    if (old_head > BUFFER_SIZE*2||old_head==0) {
        // Stack was empty - undo our decrement and return failure
        head=0;
        return INVALID_ID;
    }
    // Read the ID from the position we reserved (old_head)
    uint popped_id = buffer_data[old_head-1];
    
    return popped_id;
}


// Get current statistics (for debugging/monitoring)
void free_list_stats(out uint size, out uint capacity) {
    size = head;
    capacity = BUFFER_SIZE;
}
