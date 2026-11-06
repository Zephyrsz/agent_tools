base_url="https://huggingface.co/mlx-community/Qwen3.8-27B-8bit/resolve/main/"

for shard in {1..6}; do
    printf -v shard_number '%05d' "$shard"
    bash download_hf_model.sh "${base_url}/model-${shard_number}-of-00006.safetensors" .
done
