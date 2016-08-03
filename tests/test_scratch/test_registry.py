from dodocker import run_dodocker_cli
import os, pytest

class TestRegistryParams:
    def test_set_registry_params(self, tmpdir_copy, capsys):
        """ 
        Capturing to output.txt is not possible since this feature is
        provided by doit, which is not started for configuration code.
        So we use capsys.
        """
        run_dodocker_cli(['config','--list'])
        out, err = capsys.readouterr()
        assert 'registry_path : localhost:5000' in out
        assert 'insecure : True' in out

        run_dodocker_cli(['config','--set-secure'])
        run_dodocker_cli(['config','--list'])
        out, err = capsys.readouterr()
        assert 'registry_path : localhost:5000' in out
        assert 'insecure : False' in out
        
        run_dodocker_cli(['config','--set-registry-path','my.registry.com:443'])
        run_dodocker_cli(['config','--list'])
        out, err = capsys.readouterr()
        assert 'registry_path : my.registry.com:443' in out
        assert 'insecure : False' in out

class TestRegistry:
    def test_given_build(self,tmpdir_copy):
        with tmpdir_copy.as_cwd():
            run_dodocker_cli(['-o','output.txt','build'])
        output = tmpdir_copy.join('output.txt').open().read()
        assert output == '\n'.join(('.  build_dodockertest/test1',
                                    '.  build_dodockertest/test2',
                                    '.  build_dodockertest/test3',
                                    ''))

    def test_upload(self, tmpdir_copy, docker_registry):
        run_dodocker_cli(['-o','output.txt','upload'])
        output = tmpdir_copy.join('output.txt').read()
        pytest.set_trace()