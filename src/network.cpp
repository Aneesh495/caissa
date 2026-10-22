#include "caissa/network.hpp"
#include <algorithm>
#include <bit>
#include <fstream>
#include <iterator>
namespace caissa {
int king_bucket(Color perspective,Square king) {
    auto s=static_cast<Square>(king^(perspective==Color::black?56:0));return (rank(s)/2)*4+file(s)/2;
}
int feature_index(Color perspective,int bucket,Piece p,Square s) {
    if(!p||bucket<0||bucket>=king_buckets||s>=64)throw std::logic_error("invalid neural feature");
    int relative=color(p)==perspective?0:1;int oriented=s^(perspective==Color::black?56:0);
    return ((bucket*12+relative*6+static_cast<int>(kind(p))-1)*64)+oriented;
}
std::uint32_t crc32(std::span<const std::uint8_t> bytes) {
    std::uint32_t crc=0xffffffffU;
    for(auto byte:bytes){crc^=byte;for(int i=0;i<8;++i)crc=(crc>>1)^((crc&1U)?0xedb88320U:0U);}return ~crc;
}
namespace {
class Reader {
public:
    explicit Reader(std::span<const std::uint8_t> data):data_(data){}
    std::uint32_t u32(){std::uint32_t v=0;for(int i=0;i<4;++i)v|=static_cast<std::uint32_t>(byte())<<(8*i);return v;}
    std::uint64_t u64(){auto lo=u32();return lo|(static_cast<std::uint64_t>(u32())<<32);}
    std::int16_t i16(){std::uint16_t v=byte();v=static_cast<std::uint16_t>(v|(static_cast<std::uint16_t>(byte())<<8));return std::bit_cast<std::int16_t>(v);}
    std::int32_t i32(){auto v=std::bit_cast<std::int32_t>(u32());if(v<-(1<<20)||v>(1<<20))throw InputError("network bias exceeds arithmetic contract");return v;}
    std::string text(std::size_t n){std::string s;for(std::size_t i=0;i<n;++i)s+=static_cast<char>(byte());return s;}
    std::size_t consumed()const{return offset_;}
private:
    std::span<const std::uint8_t> data_;std::size_t offset_=0;
    std::uint8_t byte(){if(offset_>=data_.size())throw InputError("truncated network");return data_[offset_++];}
};
int rounded(std::int64_t value,int divisor) {return static_cast<int>(value>=0?(value+divisor/2)/divisor:-((-value+divisor/2)/divisor));}
}
std::shared_ptr<const Network> Network::load(const std::filesystem::path& path) {
    constexpr std::size_t payload_bytes=feature_count*transformer_width*2+transformer_width*4+dense1_width*transformer_width*2*2+dense1_width*4+dense2_width*dense1_width*2+dense2_width*4+dense2_width*2+4;
    std::error_code ec;auto size=std::filesystem::file_size(path,ec);
    if(ec||size!=120+payload_bytes)throw InputError("network length incompatible or truncated");
    std::ifstream input(path,std::ios::binary);std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));
    if(!input.read(reinterpret_cast<char*>(bytes.data()),static_cast<std::streamsize>(bytes.size())))throw InputError("network read failed");
    Reader reader(bytes);if(reader.text(8)!="CAISSAN1"||reader.u32()!=1||reader.u32()!=feature_version||reader.u32()!=feature_count||reader.u32()!=transformer_width||reader.u32()!=dense1_width||reader.u32()!=dense2_width||reader.u32()!=network_scale||reader.u32()!=network_clip)throw InputError("network feature or architecture mismatch");
    auto net=std::shared_ptr<Network>(new Network);net->identity_=reader.text(64);
    if(!std::all_of(net->identity_.begin(),net->identity_.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');}))throw InputError("invalid training identity");
    if(reader.u64()!=payload_bytes)throw InputError("network payload declaration mismatch");
    net->checksum_=reader.u32();if(reader.u32()!=0)throw InputError("unsupported network header extension");
    if(crc32(std::span(bytes).subspan(120))!=net->checksum_)throw InputError("network checksum mismatch");
    net->embedding_.resize(feature_count*transformer_width);
    for(auto& value:net->embedding_)value=reader.i16();for(auto& value:net->bias0_)value=reader.i32();
    for(auto& value:net->weights1_)value=reader.i16();for(auto& value:net->bias1_)value=reader.i32();
    for(auto& value:net->weights2_)value=reader.i16();for(auto& value:net->bias2_)value=reader.i32();
    for(auto& value:net->weights3_)value=reader.i16();net->bias3_=reader.i32();
    if(reader.consumed()!=bytes.size())throw InputError("network trailing bytes");return net;
}
void Network::add(std::array<std::int32_t,transformer_width>& accumulator,int feature,int sign)const {
    auto offset=static_cast<std::size_t>(feature)*transformer_width;
    for(std::size_t j=0;j<transformer_width;++j)accumulator[j]+=sign*embedding_[offset+j];
}
Accumulator Network::refresh(const Position& p)const {
    Accumulator a;
    for(Color c:{Color::white,Color::black}) {
        auto ci=static_cast<std::size_t>(index(c));a.buckets[ci]=king_bucket(c,p.king(c));a.values[ci]=bias0_;
        for(Square s=0;s<64;++s)if(p.at(s))add(a.values[ci],feature_index(c,a.buckets[ci],p.at(s),s),1);
    }
    a.position_key=p.key();a.initialized=true;return a;
}
void Network::update(const Position& after,const Undo& before,Accumulator& a)const {
    if(!a.initialized||a.position_key!=before.key)throw std::logic_error("neural accumulator not owned by prior position");
    for(Color c:{Color::white,Color::black}) {
        auto ci=static_cast<std::size_t>(index(c));int bucket=king_bucket(c,after.king(c));
        if(bucket!=a.buckets[ci]) {
            a.values[ci]=bias0_;a.buckets[ci]=bucket;
            for(Square s=0;s<64;++s)if(after.at(s))add(a.values[ci],feature_index(c,bucket,after.at(s),s),1);
        }else for(std::uint8_t i=0;i<before.count;++i) {
            auto s=before.squares[i];auto old=before.pieces[i],now=after.at(s);
            if(old)add(a.values[ci],feature_index(c,bucket,old,s),-1);
            if(now)add(a.values[ci],feature_index(c,bucket,now,s),1);
        }
    }
    a.position_key=after.key();
}
int Network::evaluate(const Position& p,const Accumulator& a,bool scalar)const {
    if(!a.initialized||a.position_key!=p.key())throw std::logic_error("stale neural accumulator");
    auto dot=scalar?dot_scalar:dot_native;
    std::array<std::int16_t,transformer_width*2> input{};
    int first=index(p.side());
    for(int perspective=0;perspective<2;++perspective)for(std::size_t j=0;j<transformer_width;++j)
        input[static_cast<std::size_t>(perspective)*transformer_width+j]=static_cast<std::int16_t>(std::clamp(a.values[static_cast<std::size_t>(first^perspective)][j],0,network_clip));
    std::array<std::int16_t,dense1_width> hidden1{};
    for(std::size_t i=0;i<dense1_width;++i)hidden1[i]=static_cast<std::int16_t>(std::clamp(rounded(dot(input.data(),weights1_.data()+i*input.size(),input.size())+bias1_[i],network_scale),0,network_clip));
    std::array<std::int16_t,dense2_width> hidden2{};
    for(std::size_t i=0;i<dense2_width;++i)hidden2[i]=static_cast<std::int16_t>(std::clamp(rounded(dot(hidden1.data(),weights2_.data()+i*hidden1.size(),hidden1.size())+bias2_[i],network_scale),0,network_clip));
    auto value=dot(hidden2.data(),weights3_.data(),hidden2.size())+bias3_;
    return std::clamp(rounded(value*400,network_scale*network_scale),-mate_threshold+1,mate_threshold-1);
}
}
