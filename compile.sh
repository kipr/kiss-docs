for i in `find * -mindepth 1 -type f -iname 'compile.sh'`;
do

	cd `dirname ${i}`
	sh compile.sh
	cd - > /dev/null
done


