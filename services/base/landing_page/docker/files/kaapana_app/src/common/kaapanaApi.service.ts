import Vue from 'vue'
import request from '@/request.ts'

const kaapanaApiService = {


  helmApiPost(subUrl: any, payload: any) {
    return new Promise((resolve, reject) => {
      request.post('/kube-helm-api' + subUrl, payload).then( (response:any) => {
        console.log(response)
        resolve(response)
      }).catch((error: any) => {
        console.log('Something went wrong loading the default external wepages', error)
        alert('Helm command failed because of ' + error)
        reject(error)
      })   
    }) 
  },

  helmApiGet(subUrl: any, params: any) {
    return new Promise((resolve, reject) => {
      request.get('/kube-helm-api' + subUrl, { params } ).then( (response: any) => {
          resolve(response)
      }).catch((error: any) => {
        console.log('Something went wrong getting the dags', error)
        alert('Helm command failed because of ' + error)
        reject(error)
      })
    }) 
  },

  // launchApplication(payload: any) {
  //   return new Promise((resolve, reject) => {
  //     request.post('/flow/kaapana/api/trigger/launch-app', payload).then(response => {
  //         console.log(response)
  //         resolve(response)
  //     }).catch(error => {
  //       console.log('Something went wrong loading the default external wepages', error)
  //       // reject(error)
  //     })
  //   })
  // },

  // deleteApplication(payload: any) {
  //   return new Promise((resolve, reject) => {
  //     request.post('/flow/kaapana/api/deleteappbyrunid', payload).then(response => {
  //         console.log(response)
  //         resolve(response)
  //     }).catch(error => {
  //       console.log('Something went wrong loading the default external wepages', error)
  //       // reject(error)
  //     })
  //   })
  // },
  
  
  // getDagRuns() {
  //   return new Promise((resolve, reject) => {
  //     let getDagRunsUrl = ''
  //     if (Vue.config.productionTip === true) {
  //       getDagRunsUrl = '/flow/kaapana/api/getdagruns'
  //     } else {
  //       getDagRunsUrl = '/jsons/dagruns.json'
  //     }

  //     let params = { dag_id: 'launch-app', state: 'running' }
  //     request.get(getDagRunsUrl, { params } ).then(response => {
  //         resolve(response)
  //     }).catch(error => {
  //       console.log('Something went wrong getting the dags', error)
  //       // reject(error)
  //     })
  //   })
  // },

  // getIngressByRunId(params: any) {
  //   return new Promise((resolve, reject) => {
  //     let getIngressByRunIdUrl = ''
  //     if (Vue.config.productionTip === true) {
  //       getIngressByRunIdUrl = '/flow/kaapana/api/getingressbyrunid'
  //     } else {
  //       getIngressByRunIdUrl = '/jsons/getingressbyrunid.json'
  //     }
      
  //     request.get(getIngressByRunIdUrl, { params } ).then(response => {
  //         resolve(response)
  //     }).catch(error => {
  //         resolve('deleted') // ingress is deleted earlier than pod
  //         console.log('The ingress seems to be delete already', error)
  //       // reject(error)
  //     })
  //   })
  // },


  getExternalWebpages() {
    return new Promise((resolve, reject) => {


      request.get('/jsons/defaultExternalWebpages.json').then((response: { data: any }) => {

        const externalWebpages = response.data

        let trainingJson = {}


        for (const key1 in externalWebpages) {
          if (externalWebpages.hasOwnProperty(key1)) {
            for (const key2 in externalWebpages[key1].subSections) {
              if (externalWebpages[key1].subSections.hasOwnProperty(key2)) {
                externalWebpages[key1].subSections[key2].linkTo =
                location.protocol + '//' + location.host +  externalWebpages[key1].subSections[key2].linkTo
              }
            }
          }
        }

        let traefikUrl = ''
        if (Vue.config.productionTip === true) {
          traefikUrl = '/traefik/api/http/routers'
        } else {
          traefikUrl = '/jsons/testingTraefikResponse.json'
        }

        request.get(traefikUrl).then((response: { data: {} }) => {
          trainingJson = response.data

          for (const key1 in externalWebpages) {
            if (externalWebpages.hasOwnProperty(key1)) {
              for (const key2 in externalWebpages[key1].subSections) {
                if (externalWebpages[key1].subSections.hasOwnProperty(key2)) {
                  if (!this.checkUrl(trainingJson, externalWebpages[key1].subSections[key2].endpoint)) {
                    delete externalWebpages[key1].subSections[key2]
                  }
                }
              }
            }
          }
        }).then(() => {
          const query = {
            query: {
              exists: {field: 'dashboard'},
            },
          };

          let elasticSearchUrl = ''

          if (Vue.config.productionTip === true) {
            elasticSearchUrl = '/elasticsearch/.kibana/_search'
          } else {
            elasticSearchUrl = '/jsons/testingKibanaResponse.json'
          }

          request.get(elasticSearchUrl, {
            params: {
              source: JSON.stringify(query),
              source_content_type: 'application/json',
            },
          })
          .then((response: { data: { [x: string]: { [x: string]: any } } }) => {
            const hits = response.data['hits']['hits']

            const kibanaSubsections: {[k: string]: any} = {};

            hits.forEach((dashboard: any, index: any) => {
              kibanaSubsections['kibana' + String(index)] =
              {
                label: dashboard['_source']['dashboard']['title'],
                linkTo: location.protocol + '//' + location.host + '/meta/app/kibana#/dashboards?title=' + dashboard['_source']['dashboard']['title'] + '&embed=true&_g=()',
              }
            });

            externalWebpages.meta.subSections = Object.assign(externalWebpages.meta.subSections, kibanaSubsections) // might not work in all browsers

            resolve(externalWebpages)

          }).catch((err: any) => {
            console.log('Something went wrong with kibana', err)
            resolve(externalWebpages)
          })
        }).catch((error: any) => {
          console.log('Something went wrong with traefik', error)
          resolve(externalWebpages)
          // reject(error)
        })
      }).catch((error: any) => {
        console.log('Something went wrong loading the default external wepages', error)
        // reject(error)
      })
    })
  },
  checkUrl(trainingJson: any, endpoint: any) {
    let availableRoute = false
    for (const routes in trainingJson) {
      if (trainingJson[routes]['status'] == 'enabled') {
        if (trainingJson[routes]['rule'].slice(12,-2)==endpoint) {
          availableRoute = true
        }
      }
    }
    return availableRoute
  }
}

export default kaapanaApiService
