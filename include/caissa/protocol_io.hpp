#pragma once
#include <functional>
#include <iosfwd>
#include <memory>
#include <string>
namespace caissa {
// One channel exclusively owns the borrowed output stream until finish returns.
class ProtocolOutput {
public:
    explicit ProtocolOutput(std::ostream& output);
    ~ProtocolOutput();
    ProtocolOutput(const ProtocolOutput&)=delete;
    ProtocolOutput& operator=(const ProtocolOutput&)=delete;
    void send(std::string line);
    bool failed() const;
    bool finish();
private:
    class Impl;std::unique_ptr<Impl> impl_;
};
void read_protocol_input(std::istream& input,const std::function<bool(char)>& consume,
                         const std::function<bool()>& output_failed);
}
