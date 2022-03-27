#include "caissa/protocol_io.hpp"
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <iostream>
#include <mutex>
#include <thread>
#if defined(__unix__) || defined(__APPLE__)
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>
#endif
namespace caissa {
class ProtocolOutput::Impl {
public:
    explicit Impl(std::ostream& stream):stream_(stream) {
#if defined(__unix__) || defined(__APPLE__)
        if(&stream_==&std::cout) {
            fd_=STDOUT_FILENO;old_flags_=fcntl(fd_,F_GETFL);
            if(old_flags_<0||fcntl(fd_,F_SETFL,old_flags_|O_NONBLOCK)<0){failed_.store(true);return;}
            flags_changed_=true;
            struct sigaction ignore{};ignore.sa_handler=SIG_IGN;sigemptyset(&ignore.sa_mask);
            if(sigaction(SIGPIPE,&ignore,&old_signal_)!=0){failed_.store(true);return;}
            signal_changed_=true;writer_=std::jthread([this]{write_loop();});
        }
#endif
    }
    ~Impl(){finish();}
    void send(std::string line) {
        if(line.size()>16384){failed_.store(true);wake_.notify_all();return;}
        line+='\n';std::lock_guard lock(mutex_);
        if(failed_.load()||stopping_)return;
        if(fd_<0){stream_<<line<<std::flush;if(!stream_)failed_.store(true);return;}
        bool critical=!line.starts_with("info ");
        if(line.size()+queued_bytes_>max_queued_bytes||queue_.size()>=max_messages) {
            if(!critical){++dropped_info_;return;}
            while(!queue_.empty()&&(line.size()+queued_bytes_>max_queued_bytes||queue_.size()>=max_messages)) {
                auto discard=queue_.begin();while(discard!=queue_.end()&&discard->critical)++discard;
                if(discard==queue_.end()){failed_.store(true);wake_.notify_all();return;}
                queued_bytes_-=discard->text.size();queue_.erase(discard);++dropped_info_;
            }
        }
        queued_bytes_+=line.size();queue_.push_back({std::move(line),critical});wake_.notify_one();
    }
    bool failed()const{return failed_.load();}
    bool finish() {
        {
            std::lock_guard lock(mutex_);
            if(!stopping_){stopping_=true;finish_deadline_=std::chrono::steady_clock::now()+std::chrono::milliseconds(100);}
        }
        wake_.notify_all();if(writer_.joinable())writer_.join();
#if defined(__unix__) || defined(__APPLE__)
        if(signal_changed_){sigaction(SIGPIPE,&old_signal_,nullptr);signal_changed_=false;}
        if(flags_changed_){fcntl(fd_,F_SETFL,old_flags_);flags_changed_=false;}
#endif
        return !failed();
    }
private:
    struct Message{std::string text;bool critical;};
    static constexpr std::size_t max_queued_bytes=128*1024,max_messages=512;
    std::ostream& stream_;int fd_=-1,old_flags_=0;bool flags_changed_=false,signal_changed_=false;
    std::mutex mutex_;std::condition_variable wake_;std::deque<Message> queue_;
    std::size_t queued_bytes_=0;std::uint64_t dropped_info_=0;
    bool stopping_=false;std::chrono::steady_clock::time_point finish_deadline_{};
    std::atomic<bool> failed_{false};std::jthread writer_;
#if defined(__unix__) || defined(__APPLE__)
    struct sigaction old_signal_{};
#endif
    bool expired() {
        std::lock_guard lock(mutex_);return stopping_&&std::chrono::steady_clock::now()>=finish_deadline_;
    }
    void write_loop() {
#if defined(__unix__) || defined(__APPLE__)
        for(;;) {
            Message message;
            {
                std::unique_lock lock(mutex_);wake_.wait_for(lock,std::chrono::milliseconds(10),[&]{return !queue_.empty()||stopping_||failed();});
                if(failed())return;
                if(queue_.empty()){if(stopping_)return;continue;}
                if(stopping_&&std::chrono::steady_clock::now()>=finish_deadline_){failed_.store(true);return;}
                message=std::move(queue_.front());queue_.pop_front();queued_bytes_-=message.text.size();
            }
            std::size_t offset=0;
            while(offset<message.text.size()) {
                if(failed()||expired()){failed_.store(true);return;}
                pollfd descriptor{fd_,POLLOUT,0};int ready=poll(&descriptor,1,10);
                if(ready<0){if(errno==EINTR)continue;failed_.store(true);return;}
                if(ready==0)continue;
                if(descriptor.revents&(POLLERR|POLLHUP|POLLNVAL)){failed_.store(true);return;}
                auto count=::write(fd_,message.text.data()+offset,message.text.size()-offset);
                if(count>0)offset+=static_cast<std::size_t>(count);
                else if(count<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))continue;
                else {failed_.store(true);return;}
            }
        }
#endif
    }
};
ProtocolOutput::ProtocolOutput(std::ostream& output):impl_(std::make_unique<Impl>(output)){}
ProtocolOutput::~ProtocolOutput()=default;
void ProtocolOutput::send(std::string line){impl_->send(std::move(line));}
bool ProtocolOutput::failed()const{return impl_->failed();}
bool ProtocolOutput::finish(){return impl_->finish();}
void read_protocol_input(std::istream& input,const std::function<bool(char)>& consume,const std::function<bool()>& output_failed) {
#if defined(__unix__) || defined(__APPLE__)
    if(&input==&std::cin) {
        char bytes[4096];
        while(!output_failed()) {
            pollfd descriptor{STDIN_FILENO,POLLIN,0};int ready=poll(&descriptor,1,10);
            if(ready<0){if(errno==EINTR)continue;return;}
            if(ready==0)continue;
            if(descriptor.revents&POLLNVAL)return;
            auto count=::read(STDIN_FILENO,bytes,sizeof(bytes));
            if(count==0)return;
            if(count<0){if(errno==EINTR||errno==EAGAIN)continue;return;}
            for(ssize_t i=0;i<count;++i)if(!consume(bytes[i])||output_failed())return;
        }
        return;
    }
#endif
    char c;while(!output_failed()&&input.get(c))if(!consume(c))return;
}
}
