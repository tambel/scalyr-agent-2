source cache_lib.sh




restore_from_cache my_file ./my_file

if [ -f ./my_file ]; then
  echo "RESTORED"
else
  echo "NOT FOUND"
  echo "hi" > ./my_file
fi

save_to_cache my_file ./my_file


rm ./my_file