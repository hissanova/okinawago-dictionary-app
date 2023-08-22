update-docker :
	docker build -t oki_dict_local:latest  .
update-poetry :
	./update-dict.sh
update : update-poetry update-docker

