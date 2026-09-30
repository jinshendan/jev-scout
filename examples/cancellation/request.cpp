#include "request.h"

#include <utility>

namespace cancellation_demo {

Request::Request(Queue& queue, RequestId id) : queue_(queue), id_(id) {}

void Request::queue_completion(std::function<void()> on_complete) {
    // The queued callback does not keep its Request alive.
    std::weak_ptr<Request> weak_request = weak_from_this();
    queue_.enqueue(id_, [weak_request, on_complete = std::move(on_complete)] {
        auto request = weak_request.lock();
        if (!request || request->cancelled()) {
            return;
        }
        on_complete();
    });
}

void Request::cancel() {
    // Cancellation is a flag change here; queue removal is a separate API.
    cancelled_ = true;
}

bool Request::cancelled() const {
    return cancelled_;
}

}  // namespace cancellation_demo
