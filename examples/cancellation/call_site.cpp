#include "request.h"

#include <memory>

namespace cancellation_demo {

// A source-reading scenario, with no main(), build target, or test assertion.
// Queue outlives Request in this scope. The example has no concurrency model.
void cancellation_source_scenario() {
    Queue queue;
    auto request = std::make_shared<Request>(queue, 17);

    request->queue_completion([] {
        // A placeholder completion callback; no external side effects.
    });
    request->cancel();

    // Separate questions: is the entry queued, and will on_complete run?
    const auto pending_before_dispatch = queue.pending_count();
    queue.dispatch_one();
    (void)pending_before_dispatch;
}

}  // namespace cancellation_demo
