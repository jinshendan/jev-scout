#include "queue.h"

#include <algorithm>
#include <utility>

namespace cancellation_demo {

void Queue::enqueue(RequestId owner, std::function<void()> callback) {
    callbacks_.push_back({owner, std::move(callback)});
}

std::size_t Queue::remove_for(RequestId owner) {
    const auto before = callbacks_.size();
    const auto first_removed = std::remove_if(
        callbacks_.begin(), callbacks_.end(),
        [owner](const QueuedCallback& entry) { return entry.owner == owner; });
    callbacks_.erase(first_removed, callbacks_.end());
    return before - callbacks_.size();
}

bool Queue::dispatch_one() {
    if (callbacks_.empty()) {
        return false;
    }

    auto entry = std::move(callbacks_.front());
    callbacks_.pop_front();
    entry.callback();
    return true;
}

std::size_t Queue::pending_count() const {
    return callbacks_.size();
}

}  // namespace cancellation_demo
