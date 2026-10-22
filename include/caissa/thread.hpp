#pragma once
#include <concepts>
#include <thread>
#include <type_traits>
#include <utility>
namespace caissa {
// Cancellation belongs to SearchControl; this object exclusively owns joining.
// Its owner must outlive the callable and must not destroy it from that callable.
class JoiningThread {
public:
    JoiningThread() noexcept=default;
    template<class Function,class... Args>
        requires(!std::same_as<std::remove_cvref_t<Function>,JoiningThread>)
    explicit JoiningThread(Function&& function,Args&&... args)
        :thread_(std::forward<Function>(function),std::forward<Args>(args)...){}
    JoiningThread(JoiningThread&&) noexcept=default;
    JoiningThread& operator=(JoiningThread&& other) noexcept {
        if(this!=&other){join();thread_=std::move(other.thread_);}return *this;
    }
    JoiningThread(const JoiningThread&)=delete;
    JoiningThread& operator=(const JoiningThread&)=delete;
    ~JoiningThread(){join();}
    bool joinable()const noexcept{return thread_.joinable();}
    void join(){if(thread_.joinable())thread_.join();}
private:
    std::thread thread_;
};
}
