#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>

namespace cancellation_demo {

using RequestId = std::uint64_t;

// A deliberately small, single-threaded queue for source investigation.
class Queue {
public:
    void enqueue(RequestId owner, std::function<void()> callback);

    // Removes callbacks still in the queue for this request.
    std::size_t remove_for(RequestId owner);

    // Pops one entry before invoking its callback.
    bool dispatch_one();
    std::size_t pending_count() const;

private:
    struct QueuedCallback {
        RequestId owner;
        std::function<void()> callback;
    };

    std::deque<QueuedCallback> callbacks_;
};

}  // namespace cancellation_demo
