#include "caissa/network.hpp"
#include "caissa/search.hpp"
#include <algorithm>
#include <array>
#include <charconv>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <random>
#include <utility>

using namespace caissa;
int main(int argc,char** argv){try {
    unsigned calls=0;
    if(argc!=2)throw InputError("dense_kernel_bench calls (100..100000)");
    std::string_view text(argv[1]);auto [end,error]=std::from_chars(text.data(),text.data()+text.size(),calls);
    if(error!=std::errc{}||end!=text.data()+text.size()||calls<100||calls>100000)throw InputError("benchmark workload outside bounds");
    std::mt19937 random(961748927);
    std::array<std::int16_t,256> input{};
    std::array<std::int16_t,256*32> weights{};
    std::array<std::int32_t,32> bias{};
    std::array<std::int16_t,32> output{};
    std::cout<<std::setprecision(15);
    for(auto shape:{std::pair<std::size_t,std::size_t>{64,32},{128,32},{256,32},{32,16}}) {
        auto [columns,rows]=shape;
        for(auto& value:weights)value=static_cast<std::int16_t>(static_cast<int>(random()%255)-127);
        for(auto& value:bias)value=1048576+static_cast<int>(random()%1024)-512;
        auto run=[&](bool grouped,unsigned iterations) {
            for(std::size_t i=0;i<input.size();++i)input[i]=static_cast<std::int16_t>((i*17+3)%2048);
            std::int64_t signature=0;
            for(unsigned call=0;call<iterations;++call) {
                input[call%columns]=static_cast<std::int16_t>((call*17+11)%2048);
                if(grouped)clipped_affine(input.data(),weights.data(),bias.data(),output.data(),columns,rows,1024,2047);
                else for(std::size_t row=0;row<rows;++row) {
                    auto sum=dot_native(input.data(),weights.data()+row*columns,columns)+bias[row];
                    auto value=sum>=0?(sum+512)/1024:-((-sum+512)/1024);
                    output[row]=static_cast<std::int16_t>(std::clamp<std::int64_t>(value,0,2047));
                }
                for(std::size_t row=0;row<rows;++row)signature+=output[row];
            }
            return signature;
        };
        if(run(false,100)!=run(true,100))throw std::runtime_error("benchmark warmup signatures differ");
        for(int trial=0;trial<10;++trial) {
            std::array<std::int64_t,2> signatures{};
            for(int order=0;order<2;++order) {
                bool grouped=(order+trial)%2!=0;
                auto wall_start=monotonic_ns();auto cpu_start=std::clock();
                auto signature=run(grouped,calls);
                auto cpu_end=std::clock();auto wall_end=monotonic_ns();
                if(cpu_start==static_cast<std::clock_t>(-1)||cpu_end==static_cast<std::clock_t>(-1)||cpu_end<cpu_start)
                    throw std::runtime_error("process CPU clock unavailable or wrapped");
                signatures[static_cast<std::size_t>(grouped)]=signature;
                std::cout<<"{\"columns\":"<<columns<<",\"rows\":"<<rows<<",\"trial\":"<<trial<<",\"grouped\":"<<(grouped?"true":"false")
                         <<",\"calls\":"<<calls<<",\"wall_ns\":"<<wall_end-wall_start<<",\"process_cpu_ns\":"
                         <<static_cast<double>(cpu_end-cpu_start)*1000000000.0/CLOCKS_PER_SEC<<",\"signature\":"<<signature<<"}\n";
            }
            if(signatures[0]!=signatures[1])throw std::runtime_error("benchmark native operator signatures differ");
        }
    }
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
