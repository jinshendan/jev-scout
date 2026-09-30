#pragma once

#include "queue.h"

#include <functional>
#include <memory>

namespace cancellation_demo {

// Create Requests through shared_ptr before calling queue_completion.
class Request : public std::enable_shared_from_this<Request> {
public:
    Request(Queue& queue, RequestId id);

    void queue_completion(std::function<void()> on_complete);
    void cancel();
    bool cancelled() const;

private:
    Queue& queue_;
    RequestId id_;
    bool cancelled_ = false;
};

}  // namespace cancellation_demo
